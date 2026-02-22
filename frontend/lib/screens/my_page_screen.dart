import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/user.dart';
import '../services/api_service.dart';
import '../theme/style.dart';
import '../widgets/state_widgets.dart';
import '../utils/snackbar_utils.dart';
import '../providers/auth_provider.dart';
import '../providers/user_provider.dart';
import 'package:url_launcher/url_launcher.dart';
import 'point_screen.dart';
import 'login_screen.dart';
import 'terms_screen.dart';
import 'privacy_screen.dart';

class MyPageScreen extends ConsumerStatefulWidget {
  const MyPageScreen({super.key});

  @override
  ConsumerState<MyPageScreen> createState() => _MyPageScreenState();
}

class _MyPageScreenState extends ConsumerState<MyPageScreen> {
  bool _isSaving = false;

  final TextEditingController _companyController = TextEditingController();
  final TextEditingController _ceoController = TextEditingController();
  final TextEditingController _licensesController = TextEditingController();
  final TextEditingController _capacityController = TextEditingController();
  final TextEditingController _performanceController = TextEditingController();

  String? _selectedLocation;
  final List<String> _locations = [
    "서울특별시", "부산광역시", "대구광역시", "인천광역시",
    "광주광역시", "대전광역시", "울산광역시", "세종특별자치시",
    "경기도", "강원도", "충청북도", "충청남도",
    "전라북도", "전라남도", "경상북도", "경상남도", "제주특별자치도",
  ];

  bool _controllersInitialized = false;

  @override
  void initState() {
    super.initState();
    ref.read(userProvider.notifier).loadUser();
  }

  @override
  void dispose() {
    _companyController.dispose();
    _ceoController.dispose();
    _licensesController.dispose();
    _capacityController.dispose();
    _performanceController.dispose();
    super.dispose();
  }

  void _populateControllers(User user) {
    if (_controllersInitialized) return;
    _controllersInitialized = true;
    _companyController.text = user.companyName ?? "";
    _ceoController.text = user.ceoName ?? "";
    _licensesController.text = user.licenses ?? "";
    _selectedLocation = user.location;
    _capacityController.text =
        user.capacityCost != null ? _formatNumber(user.capacityCost!) : "";
    _performanceController.text = user.performanceRecord != null
        ? _formatNumber(user.performanceRecord!)
        : "";
  }

  Future<void> _saveUser() async {
    HapticFeedback.lightImpact();
    setState(() => _isSaving = true);

    try {
      final data = {
        "company_name": _companyController.text.trim(),
        "ceo_name": _ceoController.text.trim(),
        "licenses": _licensesController.text.trim(),
        "location": _selectedLocation,
        "capacity_cost":
            int.tryParse(_capacityController.text.replaceAll(',', '')) ?? 0,
        "performance_record":
            int.tryParse(_performanceController.text.replaceAll(',', '')) ?? 0,
      };

      await ref.read(userProvider.notifier).updateUser(data);
      setState(() => _isSaving = false);

      HapticFeedback.mediumImpact();
      if (mounted) {
        SnackBarUtils.showSuccess(context, "정보가 저장되었어요");
      }
    } catch (e) {
      setState(() => _isSaving = false);
      if (mounted) {
        SnackBarUtils.showError(context, "저장에 실패했어요. 다시 시도해주세요");
      }
    }
  }

  String _formatNumber(int number) {
    return number.toString().replaceAllMapped(
          RegExp(r'(\d{1,3})(?=(\d{3})+(?!\d))'),
          (Match m) => '${m[1]},',
        );
  }

  String _formatCurrency(int? amount) {
    if (amount == null || amount == 0) return "-";
    if (amount >= 100000000) {
      return "${(amount / 100000000).toStringAsFixed(1)}억원";
    } else if (amount >= 10000) {
      return "${(amount / 10000).toStringAsFixed(0)}만원";
    }
    return "${_formatNumber(amount)}원";
  }

  @override
  Widget build(BuildContext context) {
    final userState = ref.watch(userProvider);

    return Scaffold(
      backgroundColor: AppColors.backgroundGrey,
      appBar: AppBar(
        title: const Text("마이페이지"),
        backgroundColor: AppColors.surfaceWhite,
        foregroundColor: AppColors.textMain,
        elevation: 0,
      ),
      body: userState.when(
        loading: () => const LoadingStateWidget(
          message: "정보를 불러오는 중...",
          skeletonCount: 2,
        ),
        error: (error, _) {
          if (error is AuthException) {
            WidgetsBinding.instance.addPostFrameCallback((_) {
              if (mounted) {
                Navigator.pushAndRemoveUntil(
                  context,
                  MaterialPageRoute(builder: (_) => const LoginScreen()),
                  (_) => false,
                );
              }
            });
            return const SizedBox.shrink();
          }
          return ErrorStateWidget(
            title: "정보를 불러오지 못했어요",
            message: "네트워크 연결을 확인해주세요",
            onRetry: () => ref.read(userProvider.notifier).loadUser(),
          );
        },
        data: (user) {
          if (user == null) {
            return const LoadingStateWidget(
              message: "정보를 불러오는 중...",
              skeletonCount: 2,
            );
          }
          _populateControllers(user);
          return _buildContent(user);
        },
      ),
    );
  }

  Widget _buildContent(User user) {
    return SingleChildScrollView(
      child: Column(
        children: [
          _buildProfileHeader(user),
          const SizedBox(height: 12),
          _buildSectionCard(
            title: "기본 정보",
            icon: Icons.business_rounded,
            children: [
              _buildTextField(controller: _companyController, label: "회사명", hint: "회사명을 입력해주세요", icon: Icons.apartment_rounded),
              _buildTextField(controller: _ceoController, label: "대표자명", hint: "대표자 이름을 입력해주세요", icon: Icons.person_rounded),
            ],
          ),
          _buildSectionCard(
            title: "자격 정보",
            icon: Icons.verified_rounded,
            children: [
              _buildDropdownField(label: "사업장 소재지", value: _selectedLocation, items: _locations, icon: Icons.location_on_rounded, onChanged: (val) => setState(() => _selectedLocation = val)),
              _buildTextField(controller: _licensesController, label: "보유 면허", hint: "예: 전기공사업, 소방시설업", icon: Icons.card_membership_rounded, helperText: "쉼표(,)로 구분하여 입력해주세요"),
            ],
          ),
          _buildSectionCard(
            title: "실적 정보",
            icon: Icons.analytics_rounded,
            children: [
              _buildTextField(controller: _capacityController, label: "시공능력평가액", hint: "0", icon: Icons.account_balance_rounded, keyboardType: TextInputType.number, suffix: "원", helperText: "입찰 참가자격 심사에 사용됩니다"),
              _buildTextField(controller: _performanceController, label: "최근 실적 합계", hint: "0", icon: Icons.trending_up_rounded, keyboardType: TextInputType.number, suffix: "원"),
            ],
          ),
          Padding(
            padding: const EdgeInsets.all(20),
            child: SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: _isSaving ? null : _saveUser,
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.primaryBlue,
                  foregroundColor: Colors.white,
                  disabledBackgroundColor: AppColors.primaryBlue.withOpacity(0.5),
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  elevation: 0,
                ),
                child: _isSaving
                    ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                    : const Text("저장하기", style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
              ),
            ),
          ),
          _buildAppInfoSection(),
          const SizedBox(height: 32),
        ],
      ),
    );
  }

  Widget _buildProfileHeader(User user) {
    return Container(
      width: double.infinity, padding: const EdgeInsets.all(24), color: AppColors.surfaceWhite,
      child: Column(children: [
        Container(width: 80, height: 80, decoration: BoxDecoration(color: AppColors.primaryBlue.withOpacity(0.1), borderRadius: BorderRadius.circular(40)),
          child: const Icon(Icons.person_rounded, size: 40, color: AppColors.primaryBlue)),
        const SizedBox(height: 16),
        Text(user.companyName?.isNotEmpty == true ? user.companyName! : "회사 정보를 입력해주세요",
          style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: user.companyName?.isNotEmpty == true ? AppColors.textMain : AppColors.textSub)),
        const SizedBox(height: 4),
        Text(user.email ?? "-", style: const TextStyle(fontSize: 14, color: AppColors.textSub)),
        const SizedBox(height: 20),
        Container(
          padding: const EdgeInsets.all(16), decoration: BoxDecoration(color: AppColors.backgroundGrey, borderRadius: BorderRadius.circular(12)),
          child: Row(children: [
            Expanded(child: GestureDetector(
              onTap: () { HapticFeedback.lightImpact(); Navigator.push(context, MaterialPageRoute(builder: (_) => const PointScreen())); },
              child: _buildStatItem(label: "보유 포인트", value: "${_formatNumber(user.points)}P", icon: Icons.monetization_on_rounded, color: AppColors.primaryBlue))),
            Container(width: 1, height: 40, color: AppColors.divider),
            Expanded(child: _buildStatItem(label: "시공능력", value: _formatCurrency(user.capacityCost), icon: Icons.account_balance_rounded, color: AppColors.safeGreen)),
          ])),
      ]),
    );
  }

  Widget _buildStatItem({required String label, required String value, required IconData icon, required Color color}) {
    return Column(children: [
      Icon(icon, size: 24, color: color), const SizedBox(height: 8),
      Text(value, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.textMain)),
      const SizedBox(height: 2),
      Text(label, style: const TextStyle(fontSize: 12, color: AppColors.textSub)),
    ]);
  }

  Widget _buildSectionCard({required String title, required IconData icon, required List<Widget> children}) {
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 20, vertical: 6), padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(color: AppColors.surfaceWhite, borderRadius: BorderRadius.circular(16),
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.03), blurRadius: 10, offset: const Offset(0, 2))]),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [Icon(icon, size: 20, color: AppColors.primaryBlue), const SizedBox(width: 8),
          Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.textMain))]),
        const SizedBox(height: 20), ...children,
      ]),
    );
  }

  Widget _buildTextField({required TextEditingController controller, required String label, required String hint, required IconData icon, String? helperText, String? suffix, TextInputType keyboardType = TextInputType.text}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: AppColors.textSub)),
        const SizedBox(height: 8),
        TextField(controller: controller, keyboardType: keyboardType,
          style: const TextStyle(fontSize: 15, color: AppColors.textMain),
          decoration: InputDecoration(hintText: hint, hintStyle: TextStyle(color: AppColors.textSub.withOpacity(0.5)),
            prefixIcon: Icon(icon, size: 20, color: AppColors.textSub), suffixText: suffix,
            suffixStyle: const TextStyle(fontSize: 14, color: AppColors.textSub),
            filled: true, fillColor: AppColors.backgroundGrey,
            border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
            focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: const BorderSide(color: AppColors.primaryBlue, width: 1.5)),
            contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14))),
        if (helperText != null) ...[const SizedBox(height: 6), Text(helperText, style: TextStyle(fontSize: 12, color: AppColors.textSub.withOpacity(0.7)))],
      ]),
    );
  }

  Widget _buildDropdownField({required String label, required String? value, required List<String> items, required IconData icon, required ValueChanged<String?> onChanged}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: AppColors.textSub)),
        const SizedBox(height: 8),
        DropdownButtonFormField<String>(initialValue: value, isExpanded: true,
          icon: const Icon(Icons.keyboard_arrow_down_rounded),
          style: const TextStyle(fontSize: 15, color: AppColors.textMain),
          decoration: InputDecoration(prefixIcon: Icon(icon, size: 20, color: AppColors.textSub),
            filled: true, fillColor: AppColors.backgroundGrey,
            border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
            focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: const BorderSide(color: AppColors.primaryBlue, width: 1.5)),
            contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14)),
          hint: Text("선택해주세요", style: TextStyle(color: AppColors.textSub.withOpacity(0.5))),
          items: items.map((e) => DropdownMenuItem(value: e, child: Text(e))).toList(),
          onChanged: onChanged),
      ]),
    );
  }

  Widget _buildAppInfoSection() {
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 20), padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(color: AppColors.surfaceWhite, borderRadius: BorderRadius.circular(16),
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.03), blurRadius: 10, offset: const Offset(0, 2))]),
      child: Column(children: [
        _buildInfoRow(icon: Icons.info_outline_rounded, label: "앱 버전", value: "2.2.0"),
        const Divider(height: 24),
        _buildInfoRow(icon: Icons.description_outlined, label: "이용약관", showArrow: true, onTap: () { HapticFeedback.lightImpact(); Navigator.push(context, MaterialPageRoute(builder: (_) => const TermsScreen())); }),
        const Divider(height: 24),
        _buildInfoRow(icon: Icons.privacy_tip_outlined, label: "개인정보처리방침", showArrow: true, onTap: () { HapticFeedback.lightImpact(); Navigator.push(context, MaterialPageRoute(builder: (_) => const PrivacyScreen())); }),
        const Divider(height: 24),
        _buildInfoRow(icon: Icons.help_outline_rounded, label: "문의하기", showArrow: true, onTap: () { HapticFeedback.lightImpact(); launchUrl(Uri.parse('mailto:support@bideasy.kr?subject=[BidEasy] 문의하기')); }),
        const Divider(height: 24),
        _buildInfoRow(icon: Icons.logout_rounded, label: "로그아웃", isDestructive: true, onTap: () => _showLogoutDialog()),
      ]),
    );
  }

  Widget _buildInfoRow({required IconData icon, required String label, String? value, bool showArrow = false, bool isDestructive = false, VoidCallback? onTap}) {
    return InkWell(onTap: onTap, borderRadius: BorderRadius.circular(8),
      child: Padding(padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(children: [
          Icon(icon, size: 20, color: isDestructive ? AppColors.dangerRed : AppColors.textSub),
          const SizedBox(width: 12),
          Expanded(child: Text(label, style: TextStyle(fontSize: 15, color: isDestructive ? AppColors.dangerRed : AppColors.textMain))),
          if (value != null) Text(value, style: const TextStyle(fontSize: 14, color: AppColors.textSub)),
          if (showArrow) const Icon(Icons.chevron_right_rounded, size: 20, color: AppColors.textSub),
        ])));
  }

  void _showLogoutDialog() {
    HapticFeedback.mediumImpact();
    showDialog(context: context, builder: (context) => AlertDialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      title: const Text("로그아웃", style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
      content: const Text("정말 로그아웃하시겠어요?", style: TextStyle(fontSize: 15)),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text("취소", style: TextStyle(color: AppColors.textSub))),
        TextButton(onPressed: () async {
          Navigator.pop(context);
          HapticFeedback.mediumImpact();
          await ref.read(authProvider.notifier).logout();
          if (mounted) { Navigator.pushAndRemoveUntil(context, MaterialPageRoute(builder: (_) => const LoginScreen()), (_) => false); }
        }, child: const Text("로그아웃", style: TextStyle(color: AppColors.dangerRed))),
      ],
    ));
  }
}
