import 'package:flutter/material.dart';
import '../theme/style.dart';

class TermsScreen extends StatelessWidget {
  const TermsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.backgroundGrey,
      appBar: AppBar(
        title: const Text(
          '이용약관',
          style: TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.w700,
            color: AppColors.textMain,
          ),
        ),
        backgroundColor: AppColors.surfaceWhite,
        foregroundColor: AppColors.textMain,
        elevation: 0,
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Container(
          padding: const EdgeInsets.all(20),
          decoration: BoxDecoration(
            color: AppColors.surfaceWhite,
            borderRadius: BorderRadius.circular(16),
          ),
          child: const Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _SectionTitle('제1조 (목적)'),
              _SectionBody(
                '이 약관은 BidEasy(이하 "서비스")가 제공하는 공공 입찰 정보 조회, '
                '투찰가 계산, AI 분석 등의 서비스 이용에 관한 조건과 절차를 규정함을 목적으로 합니다.',
              ),
              SizedBox(height: 20),
              _SectionTitle('제2조 (정의)'),
              _SectionBody(
                '① "서비스"란 BidEasy가 제공하는 공공 입찰 관련 정보 조회, 투찰가 계산기, '
                'AI 기반 공고 분석, 포인트 시스템 등의 기능을 말합니다.\n'
                '② "회원"이란 서비스에 가입하여 이용 계약을 체결한 자를 말합니다.\n'
                '③ "포인트"란 서비스 내 유료 기능을 이용하기 위해 충전하는 가상 화폐를 말합니다.',
              ),
              SizedBox(height: 20),
              _SectionTitle('제3조 (약관의 효력 및 변경)'),
              _SectionBody(
                '① 이 약관은 서비스를 이용하고자 하는 모든 회원에 대하여 그 효력을 발생합니다.\n'
                '② 서비스는 합리적인 사유가 발생할 경우 관련 법령에 위배되지 않는 범위에서 '
                '이 약관을 변경할 수 있으며, 변경된 약관은 서비스 내 공지사항을 통해 안내합니다.\n'
                '③ 회원이 변경된 약관에 동의하지 않을 경우 서비스 이용을 중단하고 탈퇴할 수 있습니다.',
              ),
              SizedBox(height: 20),
              _SectionTitle('제4조 (서비스 이용)'),
              _SectionBody(
                '① 서비스는 회원에게 다음의 기능을 제공합니다:\n'
                '  - 공공 입찰 공고 조회 및 검색\n'
                '  - 투찰가 계산기 (사정률 기반 안전 투찰가 산출)\n'
                '  - AI 기반 공고 분석 (위험요소 탐지, 자격 검증)\n'
                '  - 투찰가 복사 (일일 1회 무료, 추가 이용 시 포인트 차감)\n'
                '② 서비스가 제공하는 정보는 참고용이며, 실제 입찰 의사결정에 대한 책임은 회원에게 있습니다.\n'
                '③ 서비스는 낙찰가를 예측하거나 보장하지 않습니다.',
              ),
              SizedBox(height: 20),
              _SectionTitle('제5조 (구독 및 결제)'),
              _SectionBody(
                '① 서비스는 다음의 구독 요금제를 제공합니다:\n'
                '  - Free: 무료 (기본 기능 제공, AI 분석 일 1회)\n'
                '  - Pro: 월 14,900원 또는 연 140,000원 (월 11,667원, 20% 할인)\n'
                '  - Pro+: 월 29,900원 또는 연 280,000원 (월 23,333원, 20% 할인)\n'
                '② 구독 결제는 토스페이먼츠를 통한 카드 결제로 이루어집니다.\n'
                '③ 월간 구독은 결제일로부터 30일간, 연간 구독은 365일간 유효합니다.\n'
                '④ 구독 해지 시 남은 구독 기간 동안은 서비스를 계속 이용할 수 있으며, '
                '구독 기간 만료 후 Free 요금제로 전환됩니다.\n'
                '⑤ 구독 결제 후 7일 이내에 유료 기능을 이용하지 않은 경우 전액 환불이 가능합니다. '
                '그 외의 경우 남은 기간에 대한 부분 환불은 제공되지 않습니다.\n'
                '⑥ 연간 구독의 경우 결제 후 14일 이내 환불 요청 시, '
                '이용 일수에 해당하는 월간 요금을 차감한 잔액을 환불합니다.',
              ),
              SizedBox(height: 20),
              _SectionTitle('제6조 (포인트)'),
              _SectionBody(
                '① 포인트는 서비스 내 개별 유료 기능 이용을 위해 충전할 수 있습니다.\n'
                '② 포인트 충전은 토스페이먼츠를 통한 카드 결제로 이루어지며, '
                '허용된 금액(5,000원 / 10,000원 / 30,000원 / 50,000원) 단위로 충전 가능합니다.\n'
                '③ 충전된 포인트는 환불이 불가합니다. 단, 관련 법령에 따른 예외는 적용됩니다.\n'
                '④ 서비스 장애로 인한 포인트 차감 오류 시 서비스는 이를 정정합니다.',
              ),
              SizedBox(height: 20),
              _SectionTitle('제7조 (서비스 중단)'),
              _SectionBody(
                '① 서비스는 시스템 점검, 장비 교체, 천재지변 등 불가피한 사유로 '
                '일시적으로 서비스 제공을 중단할 수 있습니다.\n'
                '② 서비스 중단 시 사전에 공지하며, 불가피한 경우 사후에 공지할 수 있습니다.',
              ),
              SizedBox(height: 20),
              _SectionTitle('제8조 (면책)'),
              _SectionBody(
                '① 서비스는 공공데이터포털 API를 통해 제공되는 정보의 정확성을 보증하지 않습니다.\n'
                '② AI 분석 결과는 참고용이며, 이에 따른 입찰 결과에 대해 서비스는 책임지지 않습니다.\n'
                '③ 회원의 귀책사유로 인한 서비스 이용 장애에 대해 서비스는 책임지지 않습니다.',
              ),
              SizedBox(height: 20),
              _SectionTitle('제9조 (분쟁해결)'),
              _SectionBody(
                '① 서비스와 회원 간에 발생한 분쟁에 관한 소송은 민사소송법상의 '
                '관할법원에 제기합니다.\n'
                '② 서비스와 회원 간에 제기된 소송에는 대한민국 법을 적용합니다.',
              ),
              SizedBox(height: 20),
              _SectionBody(
                '시행일: 2026년 2월 22일',
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  final String text;
  const _SectionTitle(this.text);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Text(
        text,
        style: const TextStyle(
          fontSize: 16,
          fontWeight: FontWeight.w700,
          color: AppColors.textMain,
        ),
      ),
    );
  }
}

class _SectionBody extends StatelessWidget {
  final String text;
  const _SectionBody(this.text);

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: const TextStyle(
        fontSize: 14,
        height: 1.6,
        color: Color(0xFF4E5968),
      ),
    );
  }
}
