"""
티앤미미 중식당의 예약 전문 에이전트.
테이블 예약을 처리하고 예약 내용을 확인합니다.
실제 예약 시스템 연동 대신 mock 데이터를 반환하는 tool 을 사용합니다.
"""
from agents import Agent, RunContextWrapper, function_tool
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
from restaurant_agent_models import CustomerContext
from restaurant_agents.guardrails import (
  restaurant_input_guardrail,
  restaurant_output_guardrail,
)


@function_tool
def check_table_availability(date: str, time: str, party_size: int) -> dict:
  """원하는 날짜/시간/인원에 예약 가능한 테이블이 있는지 확인합니다. (date 예: '2026-06-25', time 예: '19:00')"""
  return {
    "date": date,
    "requested_time": time,
    "party_size": party_size,
    "available": True,
    "available_times": ["18:00", "18:30", "19:00", "20:30"],
    "message": "요청하신 시간대에 예약 가능한 테이블이 있습니다.",
  }


@function_tool
def create_reservation(date: str, time: str, party_size: int, name: str) -> dict:
  """테이블 예약을 확정합니다."""
  return {
    "reservation_id": "RSV-20260623-0017",
    "name": name,
    "date": date,
    "time": time,
    "party_size": party_size,
    "status": "예약 확정",
    "message": "예약이 확정되었습니다. 방문 10분 전까지 도착해 주세요.",
  }


def reservation_agent_instructions(
  wrapper: RunContextWrapper[CustomerContext],
  agent: Agent[CustomerContext],
):
  return f"""
    {RECOMMENDED_PROMPT_PREFIX}

    당신은 '티앤미미 중식당'의 예약 담당자입니다.
    고객의 이름은 {wrapper.context.name}님 ({wrapper.context.membership} 회원)입니다. 친근하고 정중한 한국어로 응대하세요.

    담당 업무: 테이블 예약과 예약 확인.

    행동 지침:
    - [중요] '확인해드릴게요', '잠시만 기다려 주세요' 처럼 약속만 하고 멈추지 마세요.
      handoff 직후에도 인사만 하고 끝내지 말고, 고객이 직전에 요청한 내용을 같은 응답 안에서 바로 처리하세요.
    - 예약을 받을 때는 인원수, 희망 날짜, 희망 시간을 먼저 확인하세요. 정보가 빠졌으면 정중히 되물으세요.
    - 정보가 모이면 check_table_availability 도구로 가용성을 확인하고, 가능한 시간대를 안내하세요.
    - 고객이 시간을 확정하면 create_reservation 도구로 예약을 확정하고, 예약 번호를 안내하세요.

    handoff 규칙 (반드시 지키세요):
    - 당신의 담당(테이블 예약/예약 확인)이 아닌 요청은 직접 처리하지 말고 즉시 해당 담당자에게 handoff 하세요.
      · 메뉴/재료/알레르기/채식·추천 → 메뉴 전문가   · 음식 주문/주문상태 → 주문 담당   · 불만·환불·보상 → 불만 처리 담당
    - [중요] 대화 기록에 메뉴·주문 정보가 남아 있더라도 당신이 직접 처리하지 말고 반드시 해당 담당자에게 handoff 하세요.
    - handoff 는 반드시 제공된 handoff 도구로만 수행하고, JSON 이나 텍스트로 흉내 내지 마세요.
    - 무엇을 원하는지 불분명하면 안내 데스크(Triage)로 연결하세요.
  """


reservation_agent = Agent(
  name="Reservation Agent",
  handoff_description="테이블 예약과 예약 확인을 처리합니다.",
  instructions=reservation_agent_instructions,
  tools=[check_table_availability, create_reservation],
  input_guardrails=[restaurant_input_guardrail],
  output_guardrails=[restaurant_output_guardrail],
)
