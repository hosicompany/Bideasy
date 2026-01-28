import 'package:flutter/material.dart';
import '../models/user.dart';
import '../services/api_service.dart';
import '../theme/style.dart';

class MyPageScreen extends StatefulWidget {
  const MyPageScreen({super.key});

  @override
  State<MyPageScreen> createState() => _MyPageScreenState();
}

class _MyPageScreenState extends State<MyPageScreen> {
  final ApiService _apiService = ApiService();
  bool _isLoading = true;
  User? _user;

  // Controllers
  final TextEditingController _companyController = TextEditingController();
  final TextEditingController _ceoController = TextEditingController();
  final TextEditingController _licensesController = TextEditingController();
  final TextEditingController _capacityController = TextEditingController();
  final TextEditingController _performanceController = TextEditingController();

  String? _selectedLocation;
  final List<String> _locations = [
    "서울특별시",
    "경기도",
    "인천광역시",
    "부산광역시",
    "대구광역시",
    "광주광역시",
    "전라남도",
    "경상북도",
    "충청남도",
    "강원도"
  ]; // Simplified list

  @override
  void initState() {
    super.initState();
    _loadUser();
  }

  Future<void> _loadUser() async {
    try {
      final user = await _apiService.getUserMe();
      setState(() {
        _user = user;
        _companyController.text = user.companyName ?? "";
        _ceoController.text = user.ceoName ?? "";
        _licensesController.text = user.licenses ?? "";
        _selectedLocation = user.location;
        _capacityController.text = user.capacityCost?.toString() ?? "0";
        _performanceController.text = user.performanceRecord?.toString() ?? "0";
        _isLoading = false;
      });
    } catch (e) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text("정보 로드 실패: $e")));
      setState(() => _isLoading = false);
    }
  }

  Future<void> _saveUser() async {
    setState(() => _isLoading = true);
    try {
      final data = {
        "company_name": _companyController.text,
        "ceo_name": _ceoController.text,
        "licenses": _licensesController.text,
        "location": _selectedLocation,
        "capacity_cost":
            int.tryParse(_capacityController.text.replaceAll(',', '')) ?? 0,
        "performance_record":
            int.tryParse(_performanceController.text.replaceAll(',', '')) ?? 0,
      };

      final updatedUser = await _apiService.updateUserMe(data);
      setState(() {
        _user = updatedUser;
        _isLoading = false;
      });
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text("저장되었습니다.")));
    } catch (e) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text("저장 실패: $e")));
      setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_isLoading && _user == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }

    return Scaffold(
      appBar: AppBar(title: const Text("내 정보 수정"), elevation: 0),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text("기본 정보", style: AppTextStyles.h2),
            const SizedBox(height: 16),
            TextField(
              controller: _companyController,
              decoration: const InputDecoration(
                  labelText: "회사명", border: OutlineInputBorder()),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _ceoController,
              decoration: const InputDecoration(
                  labelText: "대표자명", border: OutlineInputBorder()),
            ),
            const SizedBox(height: 32),
            const Text("자격 정보", style: AppTextStyles.h2),
            const SizedBox(height: 16),
            DropdownButtonFormField<String>(
              value: _selectedLocation,
              decoration: const InputDecoration(
                  labelText: "지역", border: OutlineInputBorder()),
              items: _locations
                  .map((e) => DropdownMenuItem(value: e, child: Text(e)))
                  .toList(),
              onChanged: (val) => setState(() => _selectedLocation = val),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _licensesController,
              decoration: const InputDecoration(
                  labelText: "보유 면허 (쉼표로 구분)",
                  hintText: "예: 전기공사업, 소방시설업",
                  border: OutlineInputBorder()),
            ),
            const SizedBox(height: 32),
            const Text("실적 정보 (단위: 원)", style: AppTextStyles.h2),
            const SizedBox(height: 16),
            TextField(
              controller: _capacityController,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                  labelText: "시공능력평가액", border: OutlineInputBorder()),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _performanceController,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                  labelText: "최근 실적 합계", border: OutlineInputBorder()),
            ),
            const SizedBox(height: 48),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: _isLoading ? null : _saveUser,
                style: ElevatedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  backgroundColor: AppColors.primaryBlue,
                  foregroundColor: Colors.white,
                ),
                child: _isLoading
                    ? const CircularProgressIndicator(color: Colors.white)
                    : const Text("저장하기",
                        style: TextStyle(
                            fontSize: 16, fontWeight: FontWeight.bold)),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
