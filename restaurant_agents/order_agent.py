"""
티앤미미 중식당의 주문 전문 에이전트.
고객의 주문을 접수하고 확인하며, 주문 상태를 안내합니다.
실제 주문 시스템 연동 대신 mock 데이터를 반환하는 tool 을 사용합니다.
"""
from agents import Agent, RunContextWrapper, function_tool
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
from restaurant_agent_models import CustomerContext
from restaurant_agents.guardrails import (
  restaurant_input_guardrail,
  restaurant_output_guardrail,
)


@function_tool
def create_order(items: str) -> dict:
  """주문을 접수합니다. items 는 쉼표로 구분한 메뉴명 문자열입니다. (예: '마파두부, 샤오롱바오')"""
  ordered = [item.strip() for item in items.split(",") if item.strip()]
  return {
    "order_id": "ORD-20260623-0042",
    "items": ordered,
    "status": "접수 완료",
    "estimated_minutes": 25,
    "message": "주문이 정상적으로 접수되었습니다.",
  }


@function_tool
def get_order_status(order_id: str) -> dict:
  """주문 번호로 현재 조리/서빙 상태를 조회합니다."""
  return {
    "order_id": order_id,
    "status": "조리 중",
    "estimated_minutes": 10,
    "message": "주방에서 조리 중이며 곧 서빙될 예정입니다.",
  }


def order_agent_instructions(
  wrapper: RunContextWrapper[CustomerContext],
  agent: Agent[CustomerContext],
):
  return f"""
    {RECOMMENDED_PROMPT_PREFIX}

    당신은 '티앤미미 중식당'의 주문 담당자입니다.
    고객의 이름은 {wrapper.context.name}님 ({wrapper.context.membership} 회원)입니다. 친근하고 정중한 한국어로 응대하세요.

    담당 업무: 주문 접수와 주문 상태 확인.

    행동 지침:
    - [중요] '확인해드릴게요', '잠시만 기다려 주세요' 처럼 약속만 하고 멈추지 마세요.
      handoff 직후에도 인사만 하고 끝내지 말고, 고객이 직전에 요청한 내용을 같은 응답 안에서 바로 처리하세요.
    - 주문을 받을 때는 메뉴명과 수량을 정확히 확인하고, 접수 전에 주문 내역을 복창해 고객의 확인을 받으세요.
    - 고객이 확인하면 create_order 도구로 주문을 접수하고, 주문 번호와 예상 시간을 안내하세요.
    - 고객이 주문 상태를 물으면 get_order_status 도구로 조회해 안내하세요.

    handoff 규칙 (반드시 지키세요):
    - 당신의 담당(주문 접수/주문 상태)이 아닌 요청은 직접 처리하지 말고 즉시 해당 담당자에게 handoff 하세요.
      · 메뉴/재료/알레르기/채식·추천 → 메뉴 전문가   · 테이블 예약 → 예약 담당   · 불만·환불·보상 → 불만 처리 담당
    - [중요] 대화 기록에 메뉴·예약 정보가 남아 있더라도 당신이 직접 처리하지 말고 반드시 해당 담당자에게 handoff 하세요.
    - handoff 는 반드시 제공된 handoff 도구로만 수행하고, JSON 이나 텍스트로 흉내 내지 마세요.
    - 무엇을 원하는지 불분명하면 안내 데스크(Triage)로 연결하세요.
  """


order_agent = Agent(
  name="Order Agent",
  handoff_description="주문 접수와 주문 상태 확인을 처리합니다.",
  instructions=order_agent_instructions,
  tools=[create_order, get_order_status],
  input_guardrails=[restaurant_input_guardrail],
  output_guardrails=[restaurant_output_guardrail],
)
