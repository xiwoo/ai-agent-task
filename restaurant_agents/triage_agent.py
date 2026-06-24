"""
티앤미미 중식당의 안내 데스크(Triage) 에이전트.
고객이 무엇을 원하는지 파악해 메뉴 / 주문 / 예약 / 불만 처리 전문 에이전트로 라우팅합니다.

[guardrail]
- 입력: 레스토랑과 무관한 질문 / 부적절한 언어를 거부합니다. (인사·스몰토크는 허용)
- 출력: 전문적·정중하고 내부 정보를 노출하지 않는 응답을 보장합니다.
  (공용 가드레일은 restaurant_agents/guardrails.py 에 정의)

이 파일에서 모든 에이전트의 handoffs 를 한 곳에 배선합니다. 전문 에이전트끼리도
서로 연결되어 있어, 라우팅 이후에도 고객 요청에 따라 자연스럽게 재-handoff 됩니다.
"""
from agents import Agent, RunContextWrapper
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
from restaurant_agent_models import CustomerContext
from restaurant_agents.guardrails import (
  restaurant_input_guardrail,
  restaurant_output_guardrail,
)
from restaurant_agents.menu_agent import menu_agent
from restaurant_agents.order_agent import order_agent
from restaurant_agents.reservation_agent import reservation_agent
from restaurant_agents.complaints_agent import complaints_agent


# --- Triage 에이전트 ------------------------------------------------------
def triage_agent_instructions(
  wrapper: RunContextWrapper[CustomerContext],
  agent: Agent[CustomerContext],
):
  return f"""
    {RECOMMENDED_PROMPT_PREFIX}

    당신은 '티앤미미 중식당'의 안내 데스크 직원입니다.
    고객의 이름은 {wrapper.context.name}님 ({wrapper.context.membership} 회원)입니다. 친근하고 정중한 한국어로 응대하세요.

    당신의 핵심 임무: 고객이 무엇을 원하는지 파악해 알맞은 전문 담당자에게 연결합니다.

    분류 가이드:
    - 🍜 메뉴/재료/알레르기/채식/가격 문의 → 메뉴 전문가
    - 📝 음식 주문, 주문 상태 → 주문 담당
    - 📅 테이블 예약, 예약 확인 → 예약 담당
    - 🙇 불만·컴플레인(음식/서비스/직원 등에 대한 불만족, 환불·보상 요청) → 불만 처리 담당

    진행 방식:
    1. 고객의 요청을 듣고, 어떤 범주인지 판단하세요.
    2. 불분명하면 1~2개의 짧은 질문으로 명확히 하세요.
    3. 연결 전에 "○○ 담당에게 연결해 드릴게요" 처럼 어디로 연결하는지 한국어로 안내하세요.
       특히 불만 고객에게는 먼저 짧게 사과하고 "도움을 드릴 수 있는 담당자에게 연결해 드릴게요" 라고 안내하세요.
    4. 알맞은 전문 담당자에게 handoff 하세요.

    여러 요청이 섞여 있으면 가장 먼저 요청한 것을 기준으로 연결하세요.
  """


triage_agent = Agent(
  name="Triage Agent",
  instructions=triage_agent_instructions,
  input_guardrails=[restaurant_input_guardrail],
  output_guardrails=[restaurant_output_guardrail],
)


# --- handoff 배선 (양방향 재-handoff) --------------------------------------
# 전문 에이전트 파일들은 서로/triage 를 import 하지 않으므로(순환 import 방지),
# 모든 에이전트를 import 하는 이 파일에서 handoffs 를 한 번에 연결한다.
triage_agent.handoffs = [menu_agent, order_agent, reservation_agent, complaints_agent]
menu_agent.handoffs = [triage_agent, order_agent, reservation_agent, complaints_agent]
order_agent.handoffs = [triage_agent, menu_agent, reservation_agent, complaints_agent]
reservation_agent.handoffs = [triage_agent, menu_agent, order_agent, complaints_agent]
complaints_agent.handoffs = [triage_agent, menu_agent, order_agent, reservation_agent]
