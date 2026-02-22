import 'package:flutter/material.dart';
import '../theme/style.dart';

class PrivacyScreen extends StatelessWidget {
  const PrivacyScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.backgroundGrey,
      appBar: AppBar(
        title: const Text(
          '개인정보처리방침',
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
              _SectionTitle('1. 수집하는 개인정보 항목'),
              _SectionBody(
                'BidEasy는 서비스 제공을 위해 다음의 개인정보를 수집합니다.\n\n'
                '필수 항목:\n'
                '  - 이메일 주소 (회원 식별 및 로그인)\n'
                '  - 비밀번호 (회원 인증, 암호화 저장)\n'
                '  - 업체명 (서비스 내 표시)\n\n'
                '선택 항목:\n'
                '  - 대표자명, 보유 면허, 소재지, 시공능력평가액 (맞춤 공고 분석)\n\n'
                '소셜 로그인 시:\n'
                '  - 카카오/네이버에서 제공하는 이메일, 닉네임, 프로필 이미지\n\n'
                '자동 수집 항목:\n'
                '  - 서비스 이용 기록, 접속 로그, IP 주소',
              ),
              SizedBox(height: 20),
              _SectionTitle('2. 개인정보의 수집 및 이용 목적'),
              _SectionBody(
                '  - 회원 가입 및 관리: 본인 확인, 서비스 부정 이용 방지\n'
                '  - 서비스 제공: 맞춤 공고 피드, 투찰가 계산, AI 분석, 자격 검증\n'
                '  - 결제 처리: 포인트 충전 및 거래 이력 관리\n'
                '  - 서비스 개선: 이용 통계 분석, 서비스 품질 향상',
              ),
              SizedBox(height: 20),
              _SectionTitle('3. 개인정보의 보유 및 이용기간'),
              _SectionBody(
                '  - 회원 탈퇴 시 즉시 파기합니다.\n'
                '  - 단, 관련 법령에 의한 보존 의무가 있는 경우:\n'
                '    · 전자상거래 등에서의 소비자 보호: 대금결제 및 재화 등의 공급에 관한 기록 (5년)\n'
                '    · 통신비밀보호법: 서비스 이용 기록, 접속 로그 (3개월)',
              ),
              SizedBox(height: 20),
              _SectionTitle('4. 개인정보의 제3자 제공'),
              _SectionBody(
                'BidEasy는 원칙적으로 회원의 개인정보를 제3자에게 제공하지 않습니다.\n'
                '다만, 다음의 경우에는 예외로 합니다:\n'
                '  - 회원이 사전에 동의한 경우\n'
                '  - 법령의 규정에 의한 경우\n\n'
                '결제 처리 시 토스페이먼츠에 주문 정보(주문번호, 금액)가 전달되며, '
                '개인 식별 정보는 전달되지 않습니다.',
              ),
              SizedBox(height: 20),
              _SectionTitle('5. 개인정보의 파기 절차 및 방법'),
              _SectionBody(
                '  - 파기 절차: 회원 탈퇴 요청 시 해당 회원의 개인정보를 즉시 파기합니다.\n'
                '  - 파기 방법:\n'
                '    · 전자적 파일: 복구 불가능한 방법으로 영구 삭제\n'
                '    · 기록물: 분쇄기로 분쇄 또는 소각',
              ),
              SizedBox(height: 20),
              _SectionTitle('6. 이용자의 권리와 행사 방법'),
              _SectionBody(
                '회원은 다음의 권리를 행사할 수 있습니다:\n'
                '  - 개인정보 열람 요구\n'
                '  - 개인정보 정정 및 삭제 요구\n'
                '  - 개인정보 처리 정지 요구\n'
                '  - 회원 탈퇴 (서비스 내 마이페이지에서 가능)\n\n'
                '권리 행사는 서비스 내 마이페이지 또는 이메일(support@bideasy.kr)을 통해 '
                '할 수 있으며, 지체 없이 처리하겠습니다.',
              ),
              SizedBox(height: 20),
              _SectionTitle('7. 개인정보의 안전성 확보 조치'),
              _SectionBody(
                'BidEasy는 개인정보의 안전성 확보를 위해 다음의 조치를 취하고 있습니다:\n'
                '  - 비밀번호 암호화 저장 (bcrypt)\n'
                '  - JWT 기반 인증 토큰 발급\n'
                '  - HTTPS 통신 암호화\n'
                '  - 접근 권한 관리 및 접속 기록 보관',
              ),
              SizedBox(height: 20),
              _SectionTitle('8. 개인정보 보호책임자'),
              _SectionBody(
                '  - 담당자: BidEasy 운영팀\n'
                '  - 이메일: support@bideasy.kr\n\n'
                '개인정보 관련 문의사항은 위 연락처로 문의해 주시기 바랍니다.',
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
