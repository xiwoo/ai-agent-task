import asyncio
import base64
import json
from typing import AsyncGenerator, List

from openai import OpenAI
from pydantic import BaseModel, Field

from google.adk.agents import BaseAgent, LlmAgent, SequentialAgent
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
# 1) Story Writer: 테마 → 구조화된 5페이지 동화. 결과를 State["story_book"] 에 저장.
# ──────────────────────────────────────────────────────────────────────────────
story_writer_agent = LlmAgent(
  name="StoryWriterAgent",
  model=MODEL,
  description=STORY_WRITER_DESCRIPTION,
  instruction=STORY_WRITER_INSTRUCTION,
  output_schema=StoryBook,
  output_key=STORY_BOOK_STATE_KEY,
)


# ──────────────────────────────────────────────────────────────────────────────
# 2) Illustrator: State["story_book"] 를 읽어 페이지마다 이미지를 결정론적으로 생성.
#    - LLM 에 도구 호출을 맡기지 않고 5페이지를 직접 순회한다(이미지 누락 방지).
#    - 페이지마다 "본문 + 시각묘사 + 이미지(인라인)" 를 하나의 이벤트로 출력하고,
#      동일 이미지를 Artifact 로도 저장한다.
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


class IllustratorAgent(BaseAgent):
  """State 의 story_book 을 읽어 페이지별 삽화를 생성/저장하는 커스텀 에이전트."""

  async def _run_async_impl(
    self, ctx: InvocationContext
  ) -> AsyncGenerator[Event, None]:
    raw = ctx.session.state.get(STORY_BOOK_STATE_KEY)
    if not raw:
      yield self._text_event(
        ctx, "⚠️ story_book 데이터가 State 에 없습니다. 먼저 동화를 작성해야 합니다."
      )
      return

    # output_schema 결과는 보통 dict 로 저장되지만, 문자열(JSON)일 수도 있어 모두 처리.
    book = json.loads(raw) if isinstance(raw, str) else raw
    print(book.get("character_sheet", ""))
    pages = book.get("pages", [])

    # 동화책 표지 안내(제목/테마)
    yield self._text_event(
      ctx,
      f"📚 **{book.get('title', '동화책')}** \n— 테마: {book.get('theme', '')}\n"
      f"총 {len(pages)}페이지를 생성합니다...",
    )

    for page in pages:
      page_no = page.get("page_number")
      text = page.get("text", "")
      visual = page.get("visual_description", "")
      image_prompt = page.get("image_prompt") or visual

      header = f"### Page {page_no}\n {text}"

      try:
        # 동기 OpenAI 호출을 이벤트 루프 밖(스레드)에서 실행.
        image_bytes = await asyncio.to_thread(_generate_image_bytes, image_prompt)
      except Exception as e:  # noqa: BLE001
        yield self._text_event(
          ctx, f"{header}\n\n❌ 이미지 생성 실패: {e}"
        )
        continue

      # Artifact 로 저장 (요구사항: 이미지가 Artifact 로 저장됨)
      filename = f"page_{page_no}.png"
      image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/png")
      version = await ctx.artifact_service.save_artifact(
        app_name=ctx.session.app_name,
        user_id=ctx.session.user_id,
        session_id=ctx.session.id,
        filename=filename,
        artifact=image_part,
      )

      # adk web 은 한 이벤트에 텍스트+이미지가 같이 있으면 이미지만 렌더링하므로,
      # 페이지 텍스트를 먼저 텍스트 이벤트로 출력한 뒤 이미지 이벤트를 출력한다.
      yield self._text_event(
        ctx, header
      )
      yield Event(
        author=self.name,
        content=types.Content(role="model", parts=[image_part]),
        actions=EventActions(artifact_delta={filename: version}),
      )

    yield self._text_event(ctx, "✅ 동화책 삽화 생성을 모두 완료했습니다!")

  def _text_event(self, ctx: InvocationContext, text: str) -> Event:
    return Event(
      author=self.name,
      content=types.Content(role="model", parts=[types.Part(text=text)]),
    )


illustrator_agent = IllustratorAgent(
  name="IllustratorAgent",
  description=ILLUSTRATOR_DESCRIPTION,
)


# ──────────────────────────────────────────────────────────────────────────────
# 3) 루트: 작가 → 일러스트레이터 순서로 실행하는 시퀀스 에이전트.
#    (adk web 이 root_agent 를 탐색한다.)
# ──────────────────────────────────────────────────────────────────────────────
root_agent = SequentialAgent(
  name="StoryBookMakerAgent",
  description=STORY_BOOK_MAKER_DESCRIPTION,
  sub_agents=[story_writer_agent, illustrator_agent],
)
