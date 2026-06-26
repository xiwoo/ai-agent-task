import dotenv
dotenv.load_dotenv()

import asyncio
import streamlit as st

from agents import (
  Runner,
  InputGuardrailTripwireTriggered,
  OutputGuardrailTripwireTriggered,
)
from restaurant_agent_models import CustomerContext
from restaurant_agents.triage_agent import triage_agent

# customer_ctx 는 이름 입력 팝업에서 이름을 받은 뒤 아래에서 생성한다.

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

# handoff 전환 배너 문구 (에이전트 이름 → 표시 문구)
HANDOFF_LABELS = {
  "Menu Agent": "🍜 메뉴 전문가에게 연결되었습니다",
  "Order Agent": "📝 주문 담당에게 연결되었습니다",
  "Reservation Agent": "📅 예약 담당에게 연결되었습니다",
  "Complaints Agent": "🙇 불만 처리 담당에게 연결되었습니다",
  "Triage Agent": "🛎️ 안내 데스크로 연결되었습니다",
}

# 각 AI 응답 말풍선 상단에 표시할 담당자 캡션 (지금 누가 응답 중인지 항상 노출)
AGENT_CAPTIONS = {
  "Triage Agent": "🛎️ 안내 데스크",
  "Menu Agent": "🍜 메뉴 전문가",
  "Order Agent": "📝 주문 담당",
  "Reservation Agent": "📅 예약 담당",
  "Complaints Agent": "🙇 불만 처리 담당",
}

# 핸드오프 도구명 → 대상 에이전트 이름 (이력 순서 보존용 마커 생성에 사용)
TRANSFER_TO_AGENT = {
  f"transfer_to_{name.lower().replace(' ', '_')}": name
  for name in HANDOFF_LABELS
}


def render_handoff_ui(agent_name):
  """handoff 발생을 채팅 메시지가 아닌 별도 UI(전환 배너)로 노출한다."""
  label = HANDOFF_LABELS.get(agent_name, f"🔄 {agent_name}에게 연결되었습니다")
  st.info(label, icon="🔄")


def open_ai_bubble(agent_name):
  """담당자 캡션이 달린 AI 응답 말풍선을 열고 텍스트 영역을 돌려준다."""
  box = st.chat_message("ai")
  box.caption(AGENT_CAPTIONS.get(agent_name, agent_name))
  return box.empty()


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
    응대 중 handoff 가 발생하면 별도 전환 배너로 노출하고, 각 응답 말풍선에는
    지금 응답하는 담당자를 캡션으로 표시한다.
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
            text_placeholder = open_ai_bubble(st.session_state["agent"].name)
          response += event.data.delta
          text_placeholder.write(response.replace("$", r"\$"))

      # handoff 발생: 응대 에이전트가 바뀌면 별도 전환 배너를 노출하고
      # 새 담당자의 응답은 다음 텍스트가 나올 때 새 말풍선에 담는다.
      # (이력 마커는 순서 보존을 위해 스트리밍 후 new_items 기준으로 생성한다)
      elif event.type == "agent_updated_stream_event":
        new_agent = event.new_agent
        if st.session_state["agent"].name != new_agent.name:
          render_handoff_ui(new_agent.name)
          st.session_state["agent"] = new_agent
          text_placeholder = None
          response = ""

    # 이번 턴에서 새로 생성된 아이템을 이력에 추가한다.
    # 핸드오프(transfer_to_*) 호출 위치에 맞춰 전환 마커를 삽입해 라이브와 같은 순서를 보장한다.
    new_items = stream.to_input_list()[len(agent_input):]
    for item in new_items:
      if item.get("type") == "function_call":
        target = TRANSFER_TO_AGENT.get(item.get("name"))
        if target:
          st.session_state["messages"].append({"type": "handoff_ui", "to": target})
      st.session_state["messages"].append(item)

  except InputGuardrailTripwireTriggered as e:
    # 입력 가드레일: off-topic 또는 부적절한 언어 → 사유에 맞는 안내로 거부
    info = e.guardrail_result.output.output_info
    if getattr(info, "is_inappropriate", False) and not getattr(info, "is_off_topic", False):
      block_msg = "정중한 대화를 부탁드려요. 메뉴 확인·예약·주문·불만 접수는 무엇이든 도와드릴게요. 🥢"
    else:
      block_msg = "저는 티앤미미 중식당 관련 질문에 대해서만 도와드리고 있어요. 메뉴를 확인하거나, 예약하거나, 음식을 주문할 수 있어요. 🥟"
    st.chat_message("ai").write(block_msg)
    # 거부된 입력은 대화 이력에서 제거한다.
    st.session_state["messages"].pop()

  except OutputGuardrailTripwireTriggered:
    # 출력 가드레일: 비전문적이거나 내부 정보가 노출되는 응답 → 안전한 문구로 대체
    safe_msg = "죄송합니다, 방금 답변을 정중하게 다시 정리할게요. 메뉴·주문·예약·불만 접수 중 무엇을 도와드릴까요?"
    if text_placeholder is not None:
      text_placeholder.write(safe_msg)
    else:
      st.chat_message("ai").write(safe_msg)


def paint_history():
  """
    인메모리에 저장된 이전 대화 이력을 출력한다.
    응답 말풍선에는 그 시점의 담당자 캡션을 함께 표시한다.
  """
  current_agent = "Triage Agent"
  for message in st.session_state["messages"]:
    item_type = message.get("type")
    # handoff 전환은 별도 배너로 다시 그리고, 이후 담당자를 갱신한다.
    if item_type == "handoff_ui":
      render_handoff_ui(message["to"])
      current_agent = message["to"]
      continue
    if message.get("role") == "user":
      content = message["content"]
      if isinstance(content, str):
        with st.chat_message("human"):
          st.write(content)
    elif item_type == "message":
      text_placeholder = open_ai_bubble(current_agent)
      text_placeholder.write(message["content"][0]["text"].replace("$", r"\$"))


# 이름 입력 팝업: 아직 이름을 받지 않았다면(=새 세션/리셋 직후) 먼저 이름을 입력받는다.
@st.dialog("티앤미미 중식당에 오신 것을 환영합니다 🥢")
def ask_customer_name():
  st.write("응대를 시작하기 전에 성함을 알려주세요.")
  name = st.text_input("이름", placeholder="예: 홍길동")
  if st.button("시작하기", type="primary", use_container_width=True):
    if name.strip():
      st.session_state["customer_name"] = name.strip()
      st.rerun()
    else:
      st.warning("이름을 입력해 주세요.")


if "customer_name" not in st.session_state:
  ask_customer_name()
  st.stop()

# 응대 대상 고객 (입력받은 이름으로 개인화)
customer_ctx = CustomerContext(
  customer_id=1,
  name=st.session_state["customer_name"],
  membership="VIP",
)

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
    st.session_state.pop("customer_name", None)
    st.rerun()
  st.write(st.session_state["messages"])
