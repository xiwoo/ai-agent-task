import dotenv
dotenv.load_dotenv()

import asyncio
import streamlit as st
from agents import Agent, Runner, WebSearchTool

# 대화 내용을 기억하는 세션 메모리 초기화 (st.session_state 배열로 관리)
if "messages" not in st.session_state:
  st.session_state["messages"] = []


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
      - 동기부여, 자기계발 팁, 습관 형성에 관한 질문을 받으면
        먼저 Web Search Tool 로 검증된 최신 조언과 방법을 검색하세요.
      - 검색 결과를 바탕으로 실천 가능한 구체적인 단계로 정리해 제시하세요.
      - 답변은 따뜻한 격려 한마디로 마무리하세요.

      사용 가능한 도구:
      - Web Search Tool: 동기부여 콘텐츠, 자기계발 팁, 습관 형성 방법 등
        최신이거나 검증이 필요한 정보를 찾을 때 사용하세요.
    """,
    tools=[
      WebSearchTool(),
    ],
  )

  with st.chat_message("ai"):
    status_container = st.status("⏳", expanded=False)
    search_placeholder = st.empty()
    text_placeholder = st.empty()
    response = ""
    searches = []

    # 이전 대화 이력에 이번 유저 메시지를 더해 에이전트에게 전달한다.
    st.session_state["messages"].append({"role": "user", "content": message})
    stream = Runner.run_streamed(agent, st.session_state["messages"])

    async for event in stream.stream_events():
      if event.type == "raw_response_event":
        update_status(status_container, event.data.type)

        if event.data.type == "response.output_item.done":
          item = event.data.item
          if getattr(item, "type", None) == "web_search_call":
            query = get_search_query(item)
            if query:
              searches.append(f'🔍 웹 검색: "{query}"')
              search_placeholder.write("\n\n".join(searches))
        elif event.data.type == "response.output_text.delta":
          response += event.data.delta
          text_placeholder.write(response.replace("$", r"\$"))

    # 이번 턴에서 생성된 응답까지 포함한 전체 대화를 메모리에 저장한다.
    st.session_state["messages"] = stream.to_input_list()


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


# AI 와 대화한 이력 출력
paint_history()

# AI 와 대화를 위한 입력창 출력
prompt = st.chat_input("오늘 어떤 고민이 있으신가요?")

if prompt:
  with st.chat_message("human"):
    st.write(prompt)
  asyncio.run(run_agent(prompt))


with st.sidebar:
  reset = st.button("Reset memory")
  if reset:
    st.session_state["messages"] = []
    st.rerun()
  st.write(st.session_state["messages"])
