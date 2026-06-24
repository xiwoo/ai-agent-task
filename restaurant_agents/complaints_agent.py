"""
티앤미미 중식당의 불만 처리 전문 에이전트.
불만족한 고객의 감정을 공감하며 인정하고, 해결책(환불/할인/매니저 콜백)을 제시하며,
심각한 문제는 매니저에게 에스컬레이션합니다.
실제 CS 시스템 연동 대신 mock 데이터를 반환하는 tool 을 사용합니다.
"""
from agents import Agent, RunContextWrapper, function_tool
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
from restaurant_agent_models import CustomerContext
from restaurant_agents.guardrails import (
  restaurant_input_guardrail,
  restaurant_output_guardrail,
)


@function_tool
def issue_refund(order_id: str, reason: str) -> dict:
  """주문에 대한 환불을 접수합니다. (불만 해결책: 환불)"""
  return {
    "refund_id": "RFD-20260624-0007",
    "order_id": order_id,
    "reason": reason,
    "status": "환불 접수 완료",
    "message": "환불이 접수되었으며 영업일 기준 3~5일 내 처리됩니다.",
  }


@function_tool
def apply_discount_coupon(percent: int) -> dict:
  """다음 방문 시 사용할 할인 쿠폰을 발급합니다. (불만 해결책: 할인)"""
  return {
    "coupon_code": "TIANMIMI-SORRY-50",
    "discount_percent": percent,
    "valid_days": 90,
    "message": f"다음 방문 시 사용 가능한 {percent}% 할인 쿠폰을 발급해 드렸습니다.",
  }


@function_tool
def request_manager_callback(name: str, phone: str) -> dict:
  """매니저가 고객에게 직접 연락하도록 콜백을 예약합니다. (불만 해결책: 매니저 콜백)"""
  return {
    "callback_id": "CB-20260624-0011",
    "name": name,
    "phone": phone,
    "status": "콜백 예약 완료",
    "message": "담당 매니저가 영업시간 내 1시간 안에 직접 연락드릴 예정입니다.",
  }


@function_tool
def escalate_complaint(description: str, severity: str) -> dict:
  """심각한 불만을 매니저/본사에 에스컬레이션합니다. (severity 예: 'low' | 'medium' | 'high')"""
  return {
    "ticket_id": "ESC-20260624-0003",
    "severity": severity,
    "description": description,
    "status": "에스컬레이션 완료",
    "message": "매니저에게 우선 처리 건으로 전달되었습니다. 빠르게 직접 챙기겠습니다.",
  }


def complaints_agent_instructions(
  wrapper: RunContextWrapper[CustomerContext],
  agent: Agent[CustomerContext],
):
  return f"""
    {RECOMMENDED_PROMPT_PREFIX}

    당신은 '티앤미미 중식당'의 불만 처리 담당자입니다.
    고객의 이름은 {wrapper.context.name}님 ({wrapper.context.membership} 회원)입니다. 따뜻하고 진심 어린 한국어로 응대하세요.

    담당 업무: 불만족한 고객을 세심하게 응대하고, 공감하며 해결책을 제시합니다.

    [최우선 규칙 — 반드시 지키세요]
    - 가장 먼저 고객의 불쾌한 경험을 진심으로 공감하고 사과하며 인정하세요. 변명하거나 책임을 회피하지 마세요.
    - 그 다음 구체적인 해결책을 '제시'하고 고객이 고를 수 있게 하세요:
      · 환불(issue_refund)  · 다음 방문 50% 할인 쿠폰(apply_discount_coupon)  · 매니저 직접 콜백(request_manager_callback)
    - 고객이 특정 해결책을 선택하면, 그때 해당 도구를 호출해 처리하고 결과(환불/쿠폰/콜백 번호 등)를 안내하세요.
    - '확인해드릴게요', '잠시만 기다려 주세요' 처럼 약속만 하고 멈추지 마세요. 같은 응답 안에서 끝까지 처리하세요.

    에스컬레이션 기준:
    - 위생 문제, 알레르기/이물질 사고, 부상, 심한 폭언·차별 등 심각한 사안은 severity='high' 로
      escalate_complaint 를 호출해 매니저에게 즉시 에스컬레이션하세요.

    handoff 규칙 (반드시 지키세요):
    - 고객이 당신의 담당(불만 처리)이 아닌 것을 원하면, 불만 해소 여부와 무관하게 당신이 직접 응대하지 말고
      즉시 해당 담당자에게 handoff 하세요. 날짜·인원 등을 직접 되묻지 마세요.
      · 테이블 예약 → 예약 담당   · 음식 주문/주문상태 → 주문 담당   · 메뉴/재료/알레르기/채식 → 메뉴 전문가
      예) "예약 잡아줘" → 당신이 직접 묻지 말고 예약 담당에게 연결.
    - [중요] 대화 기록에 메뉴·가격·예약·주문 정보가 남아 있더라도, 그것을 당신이 직접 읊거나 정리해서 답하지 마세요.
      메뉴를 다시 보여달라는 요청도 당신이 처리하지 말고 반드시 메뉴 전문가에게 handoff 하세요.
    - handoff 는 반드시 제공된 handoff 도구로만 수행하고, JSON 이나 텍스트로 흉내 내지 마세요.
    - 무엇을 원하는지 불분명하면 안내 데스크(Triage)로 연결하세요.
  """


complaints_agent = Agent(
  name="Complaints Agent",
  handoff_description="불만·컴플레인을 공감하며 처리하고 해결책(환불/할인/매니저 콜백)을 제시합니다.",
  instructions=complaints_agent_instructions,
  tools=[issue_refund, apply_discount_coupon, request_manager_callback, escalate_complaint],
  input_guardrails=[restaurant_input_guardrail],
  output_guardrails=[restaurant_output_guardrail],
)
