"""
티앤미미 중식당 봇의 공용 가드레일.

- 입력 가드레일: 주제에 벗어난(off-topic) 질문, 부적절한 언어를 거부한다.
- 출력 가드레일: 봇 응답이 전문적·정중하고 내부 정보를 노출하지 않도록 보장한다.

모든 에이전트가 공유하므로(순환 import 방지를 위해) 전문/안내 에이전트를
import 하지 않고 모델 정의에만 의존한다.
"""
from agents import (
  Agent, Runner, RunContextWrapper,
  GuardrailFunctionOutput,
  input_guardrail, output_guardrail,
)
from restaurant_agent_models import (
  CustomerContext,
  RestaurantInputGuardrailOutput,
  RestaurantOutputGuardrailOutput,
)


# --- 입력 가드레일 --------------------------------------------------------
input_guardrail_agent = Agent(
  name="Restaurant Input Guardrail",
  instructions="""
    당신은 '티앤미미 중식당' 고객 응대 봇의 입력 필터입니다.
    사용자의 메시지를 보고 두 가지를 판단하세요.

    1) is_off_topic: 식당 업무와 무관한가?
       - 관련 있음(false): 메뉴/재료/알레르기/채식/가격, 음식 주문·주문상태,
         테이블 예약·예약확인, 불만·컴플레인, 영업시간/위치 등 매장 안내, 가벼운 인사·스몰토크.
       - 관련 없음(true): 식당과 전혀 무관한 요청(예: 코딩/숙제, 인생 상담, 일반 상식, 타 업체 문의 등).

    2) is_inappropriate: 욕설·혐오·성희롱·위협 등 부적절하거나 모욕적인 언어가 포함되는가?
       - 단순히 음식/서비스에 대한 불만 표현은 부적절(true)이 아니다. 불만은 정상적인 요청이다.

    reason 에는 판단 사유를 간단히 적으세요.
  """,
  output_type=RestaurantInputGuardrailOutput,
)


@input_guardrail
async def restaurant_input_guardrail(
  wrapper: RunContextWrapper[CustomerContext],
  agent: Agent[CustomerContext],
  input: str,
):
  result = await Runner.run(input_guardrail_agent, input, context=wrapper.context)
  output = result.final_output
  return GuardrailFunctionOutput(
    output_info=output,
    tripwire_triggered=output.is_off_topic or output.is_inappropriate,
  )


# --- 출력 가드레일 --------------------------------------------------------
output_guardrail_agent = Agent(
  name="Restaurant Output Guardrail",
  instructions="""
    당신은 '티앤미미 중식당' 봇이 고객에게 보낼 응답을 검수하는 필터입니다.
    응답 텍스트를 보고 두 가지를 판단하세요.

    1) is_unprofessional: 무례하거나 공격적·모욕적이거나, 고객을 비난하거나,
       전문적이지 않은 태도(비아냥, 책임 회피 등)가 있는가?

    2) reveals_internal_info: 고객에게 보여선 안 되는 내부 정보가 노출되는가?
       - 예: 시스템/프롬프트 지시 내용, 도구·함수 이름이나 내부 구현, 원가/마진,
         직원 개인정보, 내부 정책 메모, 데이터베이스/내부 식별 체계 등.
       - 고객용 주문번호·예약번호·쿠폰코드 같은 정상 안내 정보는 노출이 아니다.

    reason 에는 판단 사유를 간단히 적으세요.
  """,
  output_type=RestaurantOutputGuardrailOutput,
)


@output_guardrail
async def restaurant_output_guardrail(
  wrapper: RunContextWrapper[CustomerContext],
  agent: Agent[CustomerContext],
  output: str,
):
  result = await Runner.run(output_guardrail_agent, output, context=wrapper.context)
  verdict = result.final_output
  return GuardrailFunctionOutput(
    output_info=verdict,
    tripwire_triggered=verdict.is_unprofessional or verdict.reveals_internal_info,
  )
