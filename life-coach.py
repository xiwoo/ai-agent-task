import dotenv
dotenv.load_dotenv()

import os
import time
import base64
import asyncio
import streamlit as st
from openai import OpenAI
from agents import Agent, Runner, WebSearchTool, FileSearchTool, ImageGenerationTool

client = OpenAI()

# 목표/일기 문서를 검색할 vector store (ID 는 .env 에서 로드)
VECTOR_STORE_ID = os.getenv("VECTOR_STORE_ID")

# 대화 내용을 기억하는 세션 메모리 초기화 (st.session_state 배열로 관리)
if "messages" not in st.session_state:
  st.session_state["messages"] = []


# hosted tool 의 호출/결과 아이템은 출력 전용이라, 다음 턴 입력으로 다시 보내면
# Responses API 가 400 (Unknown parameter: input[N].action 등) 을 반환한다.
# 따라서 에이전트 입력에서는 이들을 제거하고 대화 텍스트(user/assistant)만 남긴다.
TOOL_CALL_TYPES = {
  "web_search_call",
  "file_search_call",
  "image_generation_call",
  "code_interpreter_call",
  "reasoning",
}


def sanitize_for_agent(items):
  """
    에이전트에 보낼 입력용으로 대화 이력을 정리한다.
    hosted tool 호출/결과 아이템을 제거하고 user/assistant 메시지만 남긴다.
  """
  cleaned = []
  for item in items:
    item_type = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
    role = item.get("role") if isinstance(item, dict) else getattr(item, "role", None)
    if item_type in TOOL_CALL_TYPES:
      continue
    if role in ("user", "assistant") or item_type == "message":
      cleaned.append(item)
  return cleaned


def get_search_query(item):
  """
    web_search_call 아이템(스트리밍 객체 또는 이력 dict)에서 검색어를 추출한다.
  """
  action = item.get("action") if isinstance(item, dict) else getattr(item, "action", None)
  if action is None:
    return None
  return action.get("query") if isinstance(action, dict) else getattr(action, "query", None)


def update_status(status_container, event):
  """
    AI 와 대화 내용 중 stream event 의 상태에 따른 출력을 지원한다.
  """
  status_messages = {
    'response.web_search_call.completed': ("✅ 웹 검색 완료", "complete"),
    'response.web_search_call.in_progress': ("🔍 웹 검색 시작", "running"),
    'response.web_search_call.searching': ("🔍 웹 검색 중...", "running"),

    'response.file_search_call.completed': ("✅ 목표 문서 검색 완료", "complete"),
    'response.file_search_call.in_progress': ("🗂️ 목표 문서 검색 시작", "running"),
    'response.file_search_call.searching': ("🗂️ 목표 문서 검색 중...", "running"),

    'response.image_generation_call.in_progress': ("🎨 이미지 생성 중...", "running"),
    'response.image_generation_call.generating': ("🎨 이미지 그리는 중...", "running"),
    'response.image_generation_call.completed': ("✅ 이미지 생성 완료", "complete"),

    'response.completed': (" ", "complete"),
  }
  if event in status_messages:
    label, state = status_messages[event]
    status_container.update(label=label, state=state)


async def run_agent(message):
  """
    유저가 입력한 내용을 라이프 코치 에이전트에게 전달하고 응답을 스트리밍한다.
  """
  agent = Agent(
    name="Life Coach",
    instructions="""
      당신은 따뜻하고 격려를 아끼지 않는 라이프 코치입니다.
      유저의 동기부여, 자기계발, 습관 형성을 돕는 것이 당신의 역할입니다.

      행동 지침:
      - 항상 한국어로, 공감하고 격려하는 친근한 톤으로 답하세요.
      - 유저를 절대 비난하지 말고, 작은 진전도 칭찬하며 응원하세요.
      - 유저의 목표나 진행 상황에 관한 질문(예: "내 운동 목표 잘 되어가?")을 받으면
        먼저 File Search Tool 로 업로드된 개인 목표/일기 문서를 조회해 맥락을 파악하세요.
      - [IMPORTANT] 아래 상황에서는 명시적으로 검색을 요청하지 않아도 반드시 Web Search Tool 도구를 이용하여 최신 정보를 검색하세요. 
        - 동기부여, 자기계발 팁, 습관 형성, 목표 달성에 관한 조언이 필요한 경우 에이전트의 판단이 아니라 검색된 최신 데이터를 반드시 활용하세요.
        - File Search Tool 로 유저 목표를 확인한 뒤, 해당 목표에 도달하지 않은 경우
        - Web Search Tool 도구를 이용하여 최신 정보를 검색한 뒤, 적절한 조언을 전달하세요.
      - 개인 목표 문서의 내용과 웹 검색 결과를 결합해, 그 사람에게 딱 맞는
        개인화된 조언을 실천 가능한 구체적인 단계로 정리해 제시하세요.
      - [IMPORTANT] 아래 상황에서는 반드시 Image Generation Tool 을 호출해 이미지를 생성하세요.
        텍스트로만 축하/격려하고 끝내지 마세요. 유저가 이미지를 명시적으로 요청하지 않아도
        아래 상황이면 먼저 이미지를 만든 다음, 짧은 격려 메시지를 덧붙이세요.
        · 유저가 목표를 달성했다고 말할 때 → 목표 달성 축하 이미지
        · 동기부여가 필요해 보일 때 → 맞춤 메시지가 담긴 동기부여 포스터
        · 비전 보드를 요청할 때 → 목표(운동, 학습, 여행 등) 테마의 비전 보드
        · 진행 상황을 정리해 줄 때 → 진행 상황을 보여주는 시각적 표현
        비전 보드를 만들 때는 먼저 File Search Tool 로 유저의 목표를 확인한 뒤,
        그 목표 테마를 반영해 이미지를 생성하세요.
      - 답변은 따뜻한 격려 한마디로 마무리하세요.

      사용 가능한 도구:
      - File Search Tool: 유저가 업로드한 개인 목표 문서와 진행 일기를 검색합니다.
        목표 달성 여부, 과거 기록, 진행 상황을 참조할 때 사용하세요.
      - Web Search Tool: 동기부여 콘텐츠, 자기계발 팁, 습관 형성 방법, 목표 달성 방법 등
        관련 조언이 필요한 경우 정보를 찾을 때 사용하세요.
      - Image Generation Tool: 비전 보드, 동기부여 포스터, 축하/진행 시각화 등
        직접적인 요청이나, 시각적 격려가 필요할 때 이미지를 생성하세요.


      [IMPORTANT] 
      동기부여, 자기계발 팁, 습관 형성, 목표 달성에 관한 조언이 필요한 경우,
      File Search Tool 로 유저 목표를 확인한 뒤, 해당 목표에 도달하지 않은 경우,
      명시적으로 검색을 요청하지 않아도 반드시 Web Search Tool 도구를 이용하여 최신 정보를 검색하세요. 
    """,
    tools=[
      FileSearchTool(vector_store_ids=[VECTOR_STORE_ID]),
      WebSearchTool(),
      ImageGenerationTool(
        tool_config = {
          "type": "image_generation",
          "quality": "low",
          "output_format": "jpeg",
          "moderation": "low",
          "partial_images": 1,
        }
      ),
    ],
  )

  with st.chat_message("ai"):
    status_container = st.status("⏳", expanded=False)
    search_placeholder = st.empty()
    image_placeholder = st.empty()
    text_placeholder = st.empty()
    response = ""
    searches = []

    # 이전 대화 이력에 이번 유저 메시지를 더한다. (표시용 이력은 전체를 유지)
    st.session_state["messages"].append({"role": "user", "content": message})
    # 에이전트에는 도구 호출 아이템을 제거한 대화 텍스트만 입력으로 보낸다.
    agent_input = sanitize_for_agent(st.session_state["messages"])
    stream = Runner.run_streamed(agent, agent_input)

    async for event in stream.stream_events():
      if event.type == "raw_response_event":
        update_status(status_container, event.data.type)

        if event.data.type == "response.output_item.done":
          item = event.data.item
          item_type = getattr(item, "type", None)
          if item_type == "web_search_call":
            query = get_search_query(item)
            if query:
              searches.append(f'🔍 웹 검색: "{query}"')
              search_placeholder.write("\n\n".join(searches))
          elif item_type == "file_search_call":
            queries = getattr(item, "queries", None) or []
            label = f'🗂️ 목표 문서 검색: "{", ".join(queries)}"' if queries else "🗂️ 목표 문서를 검색했어요"
            searches.append(label)
            search_placeholder.write("\n\n".join(searches))
        elif event.data.type == "response.image_generation_call.partial_image":
          image = base64.b64decode(event.data.partial_image_b64)
          image_placeholder.image(image)
        elif event.data.type == "response.output_text.delta":
          response += event.data.delta
          text_placeholder.write(response.replace("$", r"\$"))

    # 이번 턴에서 새로 생성된 아이템(검색/이미지/응답)만 표시용 이력에 추가한다.
    new_items = stream.to_input_list()[len(agent_input):]
    st.session_state["messages"].extend(new_items)


def paint_history():
  """
    AI 와 대화한 이력 내용을 출력한다.
  """
  for message in st.session_state["messages"]:
    if "role" in message:
      with st.chat_message(message["role"]):
        if message["role"] == "user":
          content = message["content"]
          if isinstance(content, str):
            st.write(content)
        else:
          if message["type"] == "message":
            st.write(message["content"][0]["text"].replace("$", r"\$"))

    if "type" in message:
      if message["type"] == "web_search_call":
        with st.chat_message("ai"):
          query = get_search_query(message)
          if query:
            st.write(f'🔍 웹 검색: "{query}"')
          else:
            st.write("🔍 웹을 검색했어요...")
      elif message["type"] == "file_search_call":
        with st.chat_message("ai"):
          queries = message.get("queries") or []
          if queries:
            st.write(f'🗂️ 목표 문서 검색: "{", ".join(queries)}"')
          else:
            st.write("🗂️ 목표 문서를 검색했어요")
      elif message["type"] == "image_generation_call":
        with st.chat_message("ai"):
          result = message.get("result")
          if result:
            st.image(base64.b64decode(result))


# AI 와 대화한 이력 출력
paint_history()

# AI 와 대화를 위한 입력창 출력 (목표/일기 문서 첨부 가능)
prompt = st.chat_input(
  "오늘 어떤 고민이 있으신가요? (목표 문서를 첨부할 수 있어요)",
  accept_file=True,
  file_type=["txt", "pdf"],
)

if prompt:
  # 첨부된 목표/일기 문서를 vector store 에 업로드해 검색 대상으로 등록한다.
  if prompt.files:
    for file in prompt.files:
      with st.chat_message("ai"):
        with st.status(f"⏳ '{file.name}' 업로드 중...") as status:
          uploaded = client.files.create(
            file=(file.name, file.getvalue()),
            purpose="assistants",
          )
          status.update(label=f"⏳ '{file.name}' 목표 문서 등록 중...")
          vs_file = client.vector_stores.files.create(
            vector_store_id=VECTOR_STORE_ID,
            file_id=uploaded.id,
          )
          # 임베딩/인덱싱이 끝날 때까지 대기한다.
          while vs_file.status == "in_progress":
            time.sleep(1)
            vs_file = client.vector_stores.files.retrieve(
              vector_store_id=VECTOR_STORE_ID,
              file_id=uploaded.id,
            )
          if vs_file.status == "completed":
            status.update(label=f"✅ '{file.name}' 목표 문서 등록 완료", state="complete")
          else:
            status.update(label=f"⚠️ '{file.name}' 등록 실패 ({vs_file.status})", state="error")

  # 텍스트 메시지가 있으면 코치에게 전달한다.
  if prompt.text:
    with st.chat_message("human"):
      st.write(prompt.text)
    asyncio.run(run_agent(prompt.text))


with st.sidebar:
  reset = st.button("Reset memory")
  if reset:
    st.session_state["messages"] = []
    st.rerun()
  st.write(st.session_state["messages"])
