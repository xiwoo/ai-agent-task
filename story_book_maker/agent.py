import asyncio
import base64
import json
from typing import AsyncGenerator, List, Optional

from openai import OpenAI
from pydantic import BaseModel, Field

from google.adk.agents import BaseAgent, LlmAgent, ParallelAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.models.lite_llm import LiteLlm
from google.genai import types

from .prompt import (
  STORY_WRITER_DESCRIPTION,
  STORY_WRITER_INSTRUCTION,
  ILLUSTRATOR_DESCRIPTION,
  STORY_BOOK_MAKER_DESCRIPTION,
)

# 텍스트 추론(동화 작가)은 LiteLlm 으로 OpenAI 모델을 사용한다.
MODEL = LiteLlm(model="openai/gpt-5-mini")

# 이미지 생성에 사용할 OpenAI 모델
IMAGE_MODEL = "gpt-image-1"

# 두 에이전트가 공유하는 State 키
STORY_BOOK_STATE_KEY = "story_book"

# 동화책 페이지 수(= 동시에 생성할 삽화 수)
PAGE_COUNT = 5


# ──────────────────────────────────────────────────────────────────────────────
# 동화 데이터 구조 (Story Writer 의 output_schema)
#   - 두 에이전트가 State(output_key="story_book")로 이 데이터를 공유한다.
# ──────────────────────────────────────────────────────────────────────────────
class StoryPage(BaseModel):
  """동화책 한 페이지: 본문 + 시각 묘사 + 완성된 이미지 프롬프트."""
  page_number: int = Field(description="페이지 번호 (1부터 시작)")
  text: str = Field(description="해당 페이지의 동화 본문 (한국어, 1~3문장)")
  visual_description: str = Field(description="해당 페이지 삽화의 시각적 묘사 (한국어)")
  image_prompt: str = Field(
    description=(
      "이 페이지 삽화를 그리기 위한 '완성된' 영어 이미지 생성 프롬프트. "
      "전체 동화의 style_guide(화풍)와 character_sheet(캐릭터 외형)를 매 페이지에 동일하게 포함하고, 그 뒤에 이 페이지 장면을 더해 작성한다."
    )
  )


class StoryBook(BaseModel):
  """5페이지 어린이 동화책 전체 데이터."""
  title: str = Field(description="동화책 제목")
  theme: str = Field(description="사용자가 요청한 테마")
  style_guide: str = Field(
    description="모든 페이지 삽화에 공통 적용할 아트 스타일(기법/색감/분위기)"
  )
  character_sheet: str = Field(
    description="주인공 등 핵심 캐릭터의 고정된 외형 묘사 (모든 페이지 일관성 유지용)"
  )
  pages: List[StoryPage] = Field(description="정확히 5개의 페이지")


# ──────────────────────────────────────────────────────────────────────────────
# 공용 헬퍼
# ──────────────────────────────────────────────────────────────────────────────
def _generate_image_bytes(image_prompt: str) -> bytes:
  """OpenAI Images API 로 이미지를 생성해 PNG 바이트를 반환한다 (동기 호출)."""
  client = OpenAI()
  result = client.images.generate(
    model=IMAGE_MODEL,
    prompt=image_prompt,
    size="1024x1024",
    quality="low",
  )
  return base64.b64decode(result.data[0].b64_json)


def _load_book(ctx: InvocationContext) -> dict:
  """State 에 저장된 story_book 을 dict 로 로드한다 (str/dict 모두 처리)."""
  raw = ctx.session.state.get(STORY_BOOK_STATE_KEY)
  if not raw:
    return {}
  return json.loads(raw) if isinstance(raw, str) else raw


def _find_page(book: dict, page_no: int) -> Optional[dict]:
  """book 에서 page_number 가 일치하는 페이지를 찾는다(없으면 순번으로 대체)."""
  pages = book.get("pages", [])
  for page in pages:
    if page.get("page_number") == page_no:
      return page
  if 1 <= page_no <= len(pages):
    return pages[page_no - 1]
  return None


def _text_event(author: str, text: str) -> Event:
  """텍스트만 담은 model 이벤트를 만든다."""
  return Event(
    author=author,
    content=types.Content(role="model", parts=[types.Part(text=text)]),
  )


# ──────────────────────────────────────────────────────────────────────────────
# 1) Story Writer: 테마 → 구조화된 5페이지 동화. 결과를 State["story_book"] 에 저장.
#    - 구조화 출력을 위해 LlmAgent(story_writer_llm)를 쓰되, LlmAgent 는 스스로 진행
#      메시지를 이벤트로 낼 수 없으므로, 얇은 커스텀 단계(StoryWriterAgent)로 감싸
#      "작성 중..." 을 먼저 채팅으로 표시한 뒤 내부 LlmAgent 에 위임한다.
# ──────────────────────────────────────────────────────────────────────────────
story_writer_llm = LlmAgent(
  name="StoryWriterLlm",
  model=MODEL,
  description=STORY_WRITER_DESCRIPTION,
  instruction=STORY_WRITER_INSTRUCTION,
  output_schema=StoryBook,
  output_key=STORY_BOOK_STATE_KEY,
)


class StoryWriterAgent(BaseAgent):
  """'스토리 작성 중...' 을 표시하고 내부 LlmAgent 로 동화를 작성하는 처리 단계."""

  async def _run_async_impl(
    self, ctx: InvocationContext
  ) -> AsyncGenerator[Event, None]:
    yield _text_event(self.name, "📝 스토리 작성 중...")

    async for event in self.sub_agents[0].run_async(ctx):
      # 내부 LlmAgent 가 뱉는 구조화 출력(StoryBook JSON)은 adk web 채팅에 노출하지 않는다.
      # 다만 output_key(story_book) State 저장은 event.actions.state_delta 로 이뤄지므로,
      # content 만 비우고 actions 는 그대로 둔 채 yield 해야 저장이 정상 동작한다.
      event.content = None
      yield event


story_writer_agent = StoryWriterAgent(
  name="StoryWriterAgent", sub_agents=[story_writer_llm]
)


# ──────────────────────────────────────────────────────────────────────────────
# 2) Illustrator (Parallel): 페이지마다 하나의 자식 에이전트가 삽화를 '동시에' 생성.
#    - 각 PageImageAgent 는 자기 페이지의 image_prompt 로 이미지를 만들어
#      Artifact(page_N.png) 로 저장한다. (본문/이미지 출력은 Presenter 가 담당)
#    - ParallelAgent 로 감싸 5개를 동시에 실행한다(이미지 생성 시간 단축).
# ──────────────────────────────────────────────────────────────────────────────
class PageImageAgent(BaseAgent):
  """자신에게 할당된 한 페이지의 삽화만 생성/저장하는 커스텀 에이전트."""
  page_number: int

  async def _run_async_impl(
    self, ctx: InvocationContext
  ) -> AsyncGenerator[Event, None]:
    book = _load_book(ctx)
    page = _find_page(book, self.page_number)
    if not page:
      return

    # 진행 상황을 채팅으로 표시 (병렬 실행이라 5개가 거의 동시에 뜬다).
    yield _text_event(
      self.name, f"🖼️ 이미지 {self.page_number}/{PAGE_COUNT} 생성 중..."
    )

    image_prompt = page.get("image_prompt") or page.get("visual_description", "")
    filename = f"page_{self.page_number}.png"

    try:
      # 동기 OpenAI 호출을 이벤트 루프 밖(스레드)에서 실행 → 5개가 진짜로 동시에 돈다.
      image_bytes = await asyncio.to_thread(_generate_image_bytes, image_prompt)
    except Exception as e:  # noqa: BLE001
      yield _text_event(self.name, f"❌ 페이지 {self.page_number} 이미지 생성 실패: {e}")
      return

    # Artifact 로 저장 (요구사항: 이미지가 Artifact 로 저장됨)
    image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/png")
    version = await ctx.artifact_service.save_artifact(
      app_name=ctx.session.app_name,
      user_id=ctx.session.user_id,
      session_id=ctx.session.id,
      filename=filename,
      artifact=image_part,
    )

    # 아티팩트 등록용 이벤트(콘텐츠 없음). 본문+삽화 출력은 Presenter 가 순서대로 담당.
    yield Event(
      author=self.name,
      actions=EventActions(artifact_delta={filename: version}),
    )


page_image_agents = [
  PageImageAgent(name=f"PageImageAgent_{n}", page_number=n)
  for n in range(1, PAGE_COUNT + 1)
]

illustrator_parallel_agent = ParallelAgent(
  name="IllustratorParallelAgent",
  description=ILLUSTRATOR_DESCRIPTION,
  sub_agents=page_image_agents,
)


# ──────────────────────────────────────────────────────────────────────────────
# 3) Presenter: 완성된 동화책을 제목 → 페이지 순서대로 (텍스트 + 삽화) 로 출력.
#    - 병렬 단계에서 저장한 Artifact 를 다시 읽어 페이지 순서대로 렌더링한다.
#      (ParallelAgent 는 이벤트가 뒤섞이므로, 최종 출력은 여기서 정렬해 보여준다.)
# ──────────────────────────────────────────────────────────────────────────────
class StoryBookPresenterAgent(BaseAgent):
  """State 의 동화 + 저장된 삽화를 페이지 순서대로 출력하는 커스텀 에이전트."""

  async def _run_async_impl(
    self, ctx: InvocationContext
  ) -> AsyncGenerator[Event, None]:
    yield _text_event(self.name, "📖 동화책을 완성하는 중...")
    book = _load_book(ctx)
    if not book:
      yield _text_event(
        self.name, "⚠️ story_book 데이터가 State 에 없습니다. 먼저 동화를 작성해야 합니다."
      )
      return

    pages = book.get("pages", [])
    yield _text_event(
      self.name,
      f"📚 **{book.get('title', '동화책')}**\n— 테마: {book.get('theme', '')}",
    )

    for page in sorted(pages, key=lambda p: p.get("page_number", 0)):
      page_no = page.get("page_number")
      yield _text_event(self.name, f"### Page {page_no}\n{page.get('text', '')}")

      filename = f"page_{page_no}.png"
      image_part = await ctx.artifact_service.load_artifact(
        app_name=ctx.session.app_name,
        user_id=ctx.session.user_id,
        session_id=ctx.session.id,
        filename=filename,
      )
      if image_part is not None:
        yield Event(
          author=self.name,
          content=types.Content(role="model", parts=[image_part]),
        )
      else:
        yield _text_event(self.name, f"(페이지 {page_no} 삽화를 불러오지 못했습니다.)")

    yield _text_event(self.name, "✅ 동화책이 완성되었습니다!")


presenter_agent = StoryBookPresenterAgent(name="StoryBookPresenterAgent")


# ──────────────────────────────────────────────────────────────────────────────
# 루트: 작가 → (병렬)일러스트레이터 → 프레젠터 순서로 실행하는 시퀀스 에이전트.
#    (adk web 이 root_agent 를 탐색한다.)
# ──────────────────────────────────────────────────────────────────────────────
root_agent = SequentialAgent(
  name="StoryBookMakerAgent",
  description=STORY_BOOK_MAKER_DESCRIPTION,
  sub_agents=[story_writer_agent, illustrator_parallel_agent, presenter_agent],
)
