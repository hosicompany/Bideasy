import 'dart:async';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../theme/style.dart';
import '../services/api_service.dart';
import '../models/agency_profile.dart';

/// 발주기관 프로파일링 바텀시트
/// 기관명을 탭하면 해당 기관의 과거 낙찰 패턴을 분석하여 표시합니다.
class AgencyProfileSheet extends StatefulWidget {
  final String initialOrganization;

  const AgencyProfileSheet({
    super.key,
    required this.initialOrganization,
  });

  /// Show the bottom sheet from any context.
  static void show(BuildContext context, String organization) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => AgencyProfileSheet(initialOrganization: organization),
    );
  }

  @override
  State<AgencyProfileSheet> createState() => _AgencyProfileSheetState();
}

class _AgencyProfileSheetState extends State<AgencyProfileSheet> {
  final ApiService _apiService = ApiService();
  final TextEditingController _searchController = TextEditingController();
  Timer? _debounce;

  List<Map<String, dynamic>> _searchResults = [];
  bool _isSearching = false;

  AgencyProfile? _profile;
  bool _isLoadingProfile = false;
  String? _profileError;

  @override
  void initState() {
    super.initState();
    _searchController.text = widget.initialOrganization;
    _loadProfile(widget.initialOrganization);
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _searchController.dispose();
    super.dispose();
  }

  void _onSearchChanged(String query) {
    _debounce?.cancel();
    if (query.isEmpty) {
      setState(() {
        _searchResults = [];
        _isSearching = false;
      });
      return;
    }
    _debounce = Timer(const Duration(milliseconds: 300), () {
      _searchAgencies(query);
    });
  }

  Future<void> _searchAgencies(String keyword) async {
    setState(() => _isSearching = true);
    try {
      final results = await _apiService.searchAgencies(keyword);
      if (mounted) {
        setState(() {
          _searchResults = results;
          _isSearching = false;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _searchResults = [];
          _isSearching = false;
        });
      }
    }
  }

  Future<void> _loadProfile(String organization) async {
    if (!ApiService.isLoggedIn) {
      setState(() => _profileError = '로그인 후 이용할 수 있어요');
      return;
    }

    setState(() {
      _isLoadingProfile = true;
      _profileError = null;
      _profile = null;
      _searchResults = [];
    });

    try {
      final profile = await _apiService.fetchAgencyProfile(
        organization: organization,
      );
      if (mounted) {
        setState(() {
          _profile = profile;
          _isLoadingProfile = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _profileError = '기관 프로파일을 불러올 수 없어요';
          _isLoadingProfile = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      initialChildSize: 0.75,
      minChildSize: 0.4,
      maxChildSize: 0.95,
      builder: (context, scrollController) {
        return Container(
          decoration: const BoxDecoration(
            color: AppColors.surfaceWhite,
            borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
          ),
          child: Column(
            children: [
              // Handle bar
              Container(
                margin: const EdgeInsets.only(top: 12, bottom: 8),
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: Colors.grey[300],
                  borderRadius: BorderRadius.circular(2),
                ),
              ),

              // Search bar
              Padding(
                padding:
                    const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
                child: TextField(
                  controller: _searchController,
                  onChanged: _onSearchChanged,
                  onSubmitted: (v) {
                    if (v.isNotEmpty) _loadProfile(v);
                  },
                  decoration: InputDecoration(
                    hintText: "기관명 검색",
                    hintStyle: const TextStyle(color: AppColors.textSub),
                    prefixIcon: const Icon(Icons.search_rounded,
                        color: AppColors.textSub),
                    filled: true,
                    fillColor: const Color(0xFFF2F4F6),
                    contentPadding: const EdgeInsets.symmetric(
                        horizontal: 16, vertical: 12),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: BorderSide.none,
                    ),
                  ),
                ),
              ),

              // Search autocomplete results
              if (_searchResults.isNotEmpty)
                Container(
                  constraints: const BoxConstraints(maxHeight: 180),
                  margin: const EdgeInsets.symmetric(horizontal: 20),
                  decoration: BoxDecoration(
                    color: AppColors.surfaceWhite,
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: AppColors.divider),
                    boxShadow: [
                      BoxShadow(
                        color: Colors.black.withOpacity(0.05),
                        blurRadius: 8,
                        offset: const Offset(0, 2),
                      ),
                    ],
                  ),
                  child: ListView.separated(
                    shrinkWrap: true,
                    padding: EdgeInsets.zero,
                    itemCount: _searchResults.length,
                    separatorBuilder: (_, __) =>
                        const Divider(height: 1, indent: 16, endIndent: 16),
                    itemBuilder: (context, index) {
                      final item = _searchResults[index];
                      final name =
                          item['agency_name'] as String? ?? '';
                      return ListTile(
                        dense: true,
                        title: Text(name,
                            style: const TextStyle(fontSize: 14)),
                        onTap: () {
                          _searchController.text = name;
                          _loadProfile(name);
                        },
                      );
                    },
                  ),
                ),

              if (_isSearching)
                const Padding(
                  padding: EdgeInsets.all(8),
                  child: SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                ),

              const SizedBox(height: 8),

              // Profile content
              Expanded(
                child: SingleChildScrollView(
                  controller: scrollController,
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  child: _buildProfileContent(),
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _buildProfileContent() {
    if (_isLoadingProfile) {
      return const Padding(
        padding: EdgeInsets.only(top: 60),
        child: Center(
          child: Column(
            children: [
              CircularProgressIndicator(strokeWidth: 3),
              SizedBox(height: 16),
              Text(
                "기관 데이터를 분석하고 있어요...",
                style: TextStyle(
                  fontSize: 14,
                  color: AppColors.textSub,
                ),
              ),
            ],
          ),
        ),
      );
    }

    if (_profileError != null) {
      return Padding(
        padding: const EdgeInsets.only(top: 60),
        child: Center(
          child: Column(
            children: [
              Icon(Icons.lock_outline_rounded,
                  size: 48, color: Colors.grey[400]),
              const SizedBox(height: 12),
              Text(
                _profileError!,
                style: const TextStyle(
                  fontSize: 15,
                  color: AppColors.textSub,
                ),
              ),
            ],
          ),
        ),
      );
    }

    if (_profile == null) {
      return const SizedBox.shrink();
    }

    final p = _profile!;
    final numberFormat = NumberFormat('#,###');

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Organization header
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            gradient: LinearGradient(
              colors: [
                AppColors.primaryBlue,
                AppColors.primaryBlue.withOpacity(0.8),
              ],
            ),
            borderRadius: BorderRadius.circular(14),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                p.organization,
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                  color: Colors.white,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                "최근 6개월 입찰 데이터 분석",
                style: TextStyle(
                  fontSize: 13,
                  color: Colors.white.withOpacity(0.8),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),

        // Stats grid
        Row(
          children: [
            _buildStatCard(
              label: "총 입찰",
              value: "${numberFormat.format(p.totalBids)}건",
              icon: Icons.gavel_rounded,
              color: AppColors.primaryBlue,
            ),
            const SizedBox(width: 12),
            _buildStatCard(
              label: "평균 낙찰률",
              value: p.avgWinningRate != null
                  ? "${p.avgWinningRate!.toStringAsFixed(2)}%"
                  : "-",
              icon: Icons.trending_up_rounded,
              color: AppColors.safeGreen,
            ),
          ],
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            _buildStatCard(
              label: "평균 참여업체",
              value: p.avgParticipants != null
                  ? "${p.avgParticipants!.toStringAsFixed(1)}개사"
                  : "-",
              icon: Icons.groups_rounded,
              color: Colors.orange,
            ),
            const SizedBox(width: 12),
            _buildStatCard(
              label: "평균 낙찰금액",
              value: p.avgWinningPrice != null
                  ? _formatPriceShort(p.avgWinningPrice!)
                  : "-",
              icon: Icons.payments_rounded,
              color: Colors.deepPurple,
            ),
          ],
        ),
        const SizedBox(height: 20),

        // Winning rate range
        if (p.minWinningRate != null && p.maxWinningRate != null) ...[
          const Text(
            "낙찰률 범위",
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: AppColors.textMain,
            ),
          ),
          const SizedBox(height: 10),
          _buildRateRangeBar(p),
          const SizedBox(height: 20),
        ],

        // Distribution
        if (p.winningRateDistribution.isNotEmpty) ...[
          const Text(
            "낙찰률 구간별 분포",
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: AppColors.textMain,
            ),
          ),
          const SizedBox(height: 10),
          _buildDistribution(p.winningRateDistribution),
          const SizedBox(height: 20),
        ],

        // Recommendation
        if (p.recommendation.isNotEmpty) ...[
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: AppColors.primaryBlue.withOpacity(0.05),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(
                  color: AppColors.primaryBlue.withOpacity(0.2)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Row(
                  children: [
                    Icon(Icons.lightbulb_outline_rounded,
                        size: 18, color: AppColors.primaryBlue),
                    SizedBox(width: 6),
                    Text(
                      "투찰 전략 추천",
                      style: TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w700,
                        color: AppColors.primaryBlue,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                Text(
                  p.recommendation,
                  style: const TextStyle(
                    fontSize: 14,
                    color: AppColors.textMain,
                    height: 1.5,
                  ),
                ),
              ],
            ),
          ),
        ],

        const SizedBox(height: 40),
      ],
    );
  }

  Widget _buildStatCard({
    required String label,
    required String value,
    required IconData icon,
    required Color color,
  }) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: AppColors.surfaceWhite,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppColors.divider),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, size: 20, color: color),
            const SizedBox(height: 8),
            Text(
              value,
              style: const TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                color: AppColors.textMain,
              ),
            ),
            const SizedBox(height: 2),
            Text(
              label,
              style: const TextStyle(
                fontSize: 12,
                color: AppColors.textSub,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildRateRangeBar(AgencyProfile p) {
    final min = p.minWinningRate!;
    final max = p.maxWinningRate!;
    final avg = p.avgWinningRate ?? ((min + max) / 2);

    // Normalize to 80-100 range for display
    const displayMin = 80.0;
    const displayMax = 100.0;
    final range = displayMax - displayMin;

    final minPos = ((min - displayMin) / range).clamp(0.0, 1.0);
    final maxPos = ((max - displayMin) / range).clamp(0.0, 1.0);
    final avgPos = ((avg - displayMin) / range).clamp(0.0, 1.0);

    return Column(
      children: [
        SizedBox(
          height: 40,
          child: LayoutBuilder(
            builder: (context, constraints) {
              final width = constraints.maxWidth;
              return Stack(
                children: [
                  // Track
                  Positioned(
                    top: 16,
                    left: 0,
                    right: 0,
                    child: Container(
                      height: 8,
                      decoration: BoxDecoration(
                        color: Colors.grey[200],
                        borderRadius: BorderRadius.circular(4),
                      ),
                    ),
                  ),
                  // Range fill
                  Positioned(
                    top: 16,
                    left: width * minPos,
                    width: width * (maxPos - minPos),
                    child: Container(
                      height: 8,
                      decoration: BoxDecoration(
                        color: AppColors.primaryBlue.withOpacity(0.3),
                        borderRadius: BorderRadius.circular(4),
                      ),
                    ),
                  ),
                  // Average marker
                  Positioned(
                    top: 10,
                    left: (width * avgPos) - 8,
                    child: Container(
                      width: 16,
                      height: 20,
                      decoration: BoxDecoration(
                        color: AppColors.primaryBlue,
                        borderRadius: BorderRadius.circular(4),
                      ),
                    ),
                  ),
                ],
              );
            },
          ),
        ),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text("${min.toStringAsFixed(2)}%",
                style:
                    const TextStyle(fontSize: 12, color: AppColors.textSub)),
            Text("평균 ${avg.toStringAsFixed(2)}%",
                style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: AppColors.primaryBlue)),
            Text("${max.toStringAsFixed(2)}%",
                style:
                    const TextStyle(fontSize: 12, color: AppColors.textSub)),
          ],
        ),
      ],
    );
  }

  Widget _buildDistribution(Map<String, dynamic> dist) {
    final entries = dist.entries.toList();
    if (entries.isEmpty) return const SizedBox.shrink();

    final maxVal = entries
        .map((e) => (e.value as num).toDouble())
        .reduce((a, b) => a > b ? a : b);

    return Column(
      children: entries.map((entry) {
        final ratio = maxVal > 0 ? (entry.value as num) / maxVal : 0.0;
        return Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Row(
            children: [
              SizedBox(
                width: 80,
                child: Text(
                  entry.key,
                  style: const TextStyle(
                      fontSize: 12, color: AppColors.textSub),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(3),
                  child: LinearProgressIndicator(
                    value: ratio.toDouble(),
                    minHeight: 14,
                    backgroundColor: Colors.grey[100],
                    valueColor: AlwaysStoppedAnimation<Color>(
                      AppColors.primaryBlue.withOpacity(0.6),
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              SizedBox(
                width: 36,
                child: Text(
                  "${entry.value}",
                  textAlign: TextAlign.right,
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: AppColors.textMain,
                  ),
                ),
              ),
            ],
          ),
        );
      }).toList(),
    );
  }

  String _formatPriceShort(double price) {
    if (price >= 100000000) {
      return "${(price / 100000000).toStringAsFixed(1)}억";
    } else if (price >= 10000) {
      return "${(price / 10000).toStringAsFixed(0)}만";
    }
    return NumberFormat('#,###').format(price.round());
  }
}
