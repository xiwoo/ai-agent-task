import dotenv
dotenv.load_dotenv()

import asyncio
import streamlit as st

from agents import Runner, InputGuardrailTripwireTriggered
from restaurant_agent_models import CustomerContext
from restaurant_agents.triage_agent import triage_agent

# 응대 대상 고객 (개인화용 컨텍스트)
customer_ctx = CustomerContext(
  customer_id=1,
  name="민수",
  membership="VIP",
)

# 대화 이력을 기억하는 인메모리 저장소 (단순 list)
if "messages" not in st.session_state:
  st.session_state["messages"] = []

# 현재 응대 중인 에이전트 (handoff 가 일어나면 갱신됨)
if "agent" not in st.session_state:
  st.session_state["agent"] = triage_agent

# 에이전트에 다시 보낼 입력에서는 제거할 아이템 타입 (도구/핸드오프 호출 등 출력 전용)
TOOL_CALL_TYPES = {
  "function_call",
  "function_call_output",
  "reasoning",
}

# handoff 전환 UI 에 사용할 담당자 라벨 (에이전트 이름 → 표시 문구)
HANDOFF_LABELS = {
  "Menu Agent": "🍜 메뉴 전문가에게 연결되었습니다",
  "Order Agent": "📝 주문 담당에게 연결되었습니다",
  "Reservation Agent": "📅 예약 담당에게 연결되었습니다",
  "Triage Agent": "🛎️ 안내 데스크로 연결되었습니다",
}


def render_handoff_ui(agent_name):
  """handoff 발생을 채팅 메시지가 아닌 별도 UI(전환 배너)로 노출한다."""
  label = HANDOFF_LABELS.get(agent_name, f"🔄 {agent_name}에게 연결되었습니다")
  st.info(label, icon="🔄")


def sanitize_for_agent(items):
  """
    에이전트에 보낼 입력용으로 대화 이력을 정리한다.
    도구/핸드오프 호출 아이템과 화면 표시용 handoff 마커를 제거하고
    user/assistant 메시지만 남긴다.
  """
  cleaned = []
  for item in items:
    item_type = item.get("type")
    role = item.get("role")
    if item_type in TOOL_CALL_TYPES or item_type == "handoff_ui":
      continue
    if role in ("user", "assistant") or item_type == "message":
      cleaned.append(item)
  return cleaned


async def run_agent(message):
  """
    고객이 입력한 메시지를 현재 응대 에이전트에게 전달하고 응답을 스트리밍한다.
    응대 중 handoff 가 발생하면 어느 담당자에게 연결되는지 별도 UI 로 노출한다.
  """
  st.session_state["messages"].append({"role": "user", "content": message})
  # 도구 호출 아이템을 제거한 대화 텍스트만 입력으로 보낸다.
  agent_input = sanitize_for_agent(st.session_state["messages"])

  # 말풍선은 실제로 응답 텍스트가 나올 때만 지연 생성한다.
  # (텍스트 없이 handoff 만 하는 에이전트의 빈 말풍선을 방지)
  text_placeholder = None
  response = ""

  try:
    stream = Runner.run_streamed(
      st.session_state["agent"],
      agent_input,
      context=customer_ctx,
    )

    async for event in stream.stream_events():
      # 응답 텍스트 스트리밍
      if event.type == "raw_response_event":
        if event.data.type == "response.output_text.delta":
          if text_placeholder is None:
            text_placeholder = st.chat_message("ai").empty()
          response += event.data.delta
          text_placeholder.write(response.replace("$", r"\$"))

      # handoff 발생: 응대 에이전트가 바뀌면 별도 전환 UI 를 노출하고
      # 새 담당자의 응답은 다음 텍스트가 나올 때 새 말풍선에 담는다.
      elif event.type == "agent_updated_stream_event":
        new_agent = event.new_agent
        if st.session_state["agent"].name != new_agent.name:
          render_handoff_ui(new_agent.name)
          st.session_state["messages"].append({"type": "handoff_ui", "to": new_agent.name})
          st.session_state["agent"] = new_agent
          text_placeholder = None
          response = ""

    # 이번 턴에서 새로 생성된 아이템(응답/도구 호출)을 표시용 이력에 추가한다.
    new_items = stream.to_input_list()[len(agent_input):]
    st.session_state["messages"].extend(new_items)

  except InputGuardrailTripwireTriggered:
    st.chat_message("ai").write(
      "죄송합니다, 티앤미미 중식당의 메뉴·주문·예약 관련 문의만 도와드릴 수 있어요. 🥟"
    )


def paint_history():
  """
    인메모리에 저장된 이전 대화 이력을 출력한다.
  """
  for message in st.session_state["messages"]:
    item_type = message.get("type")
    # handoff 전환은 별도 UI 로 다시 그린다.
    if item_type == "handoff_ui":
      render_handoff_ui(message["to"])
      continue
    if "role" in message:
      with st.chat_message(message["role"]):
        if message["role"] == "user":
          content = message["content"]
          if isinstance(content, str):
            st.write(content)
        elif item_type == "message":
          st.write(message["content"][0]["text"].replace("$", r"\$"))


# 이전 대화 이력 출력
paint_history()

# 대화 입력창
message = st.chat_input("티앤미미 중식당입니다. 무엇을 도와드릴까요?")

if message:
  with st.chat_message("human"):
    st.write(message)
  asyncio.run(run_agent(message))


with st.sidebar:
  reset = st.button("Reset memory")
  if reset:
    st.session_state["messages"] = []
    st.session_state["agent"] = triage_agent
    st.rerun()
  st.write(st.session_state["messages"])
