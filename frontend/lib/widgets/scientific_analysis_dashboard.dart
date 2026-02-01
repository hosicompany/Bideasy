import 'package:flutter/material.dart';
import '../services/api_service.dart';

class ScientificAnalysisDashboard extends StatefulWidget {
  final String bidNo;

  const ScientificAnalysisDashboard({super.key, required this.bidNo});

  @override
  _ScientificAnalysisDashboardState createState() =>
      _ScientificAnalysisDashboardState();
}

class _ScientificAnalysisDashboardState
    extends State<ScientificAnalysisDashboard> {
  final ApiService _apiService = ApiService();
  Map<String, dynamic>? _analysisData;
  bool _isLoading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _fetchAnalysis();
  }

  Future<void> _fetchAnalysis() async {
    try {
      final data = await _apiService.fetchScientificAnalysis(widget.bidNo);
      setState(() {
        _analysisData = data;
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _error = e.toString();
        _isLoading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_isLoading) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_error != null) {
      return Center(child: Text("분석 실패: $_error"));
    }

    if (_analysisData == null) {
      return const Center(child: Text("데이터가 없습니다."));
    }

    final agency = _analysisData!['agency_profile'] ?? {};
    final monteCarlo = _analysisData!['monte_carlo'] ?? {};
    final blueOcean = _analysisData!['blue_ocean'] ?? {};

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildSectionHeader("📊 1. 발주처 성향 분석 (Agency Profiling)"),
        _buildAgencyCard(agency),
        const SizedBox(height: 20),
        _buildSectionHeader("🎰 2. 몬테카를로 시뮬레이션 (확률 1등)"),
        _buildMonteCarloCard(monteCarlo),
        const SizedBox(height: 20),
        _buildSectionHeader("🔵 3. 블루오션 전략 (경쟁 회피)"),
        _buildBlueOceanCard(blueOcean),
        const SizedBox(height: 20),
        _buildSectionHeader("📈 4. 예상 경쟁률 분석 (AI Prediction)"),
        _buildCompetitionCard(_analysisData!['competition'] ?? {}),
      ],
    );
  }

  Widget _buildSectionHeader(String title) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8.0),
      child: Text(
        title,
        style: const TextStyle(
            fontSize: 18, fontWeight: FontWeight.bold, color: Colors.indigo),
      ),
    );
  }

  Widget _buildAgencyCard(Map data) {
    return Card(
      elevation: 2,
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          children: [
            if (data['message'] != null)
              Text(data['message'], style: const TextStyle(color: Colors.grey))
            else ...[
              Text("이 발주처의 과거 낙찰 평균 사정률",
                  style: TextStyle(fontSize: 14, color: Colors.grey[700])),
              const SizedBox(height: 8),
              Text(
                "${data['avg_rate']}%",
                style: const TextStyle(
                    fontSize: 32,
                    fontWeight: FontWeight.bold,
                    color: Colors.black),
              ),
              Text("표본수: ${data['sample_size']}건",
                  style: const TextStyle(color: Colors.grey)),
            ]
          ],
        ),
      ),
    );
  }

  Widget _buildMonteCarloCard(Map data) {
    final topRates = data['top_rates'] as List? ?? [];
    return Card(
      elevation: 2,
      color: Colors.green[50],
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(data['description'] ?? "",
                style: const TextStyle(fontSize: 14)),
            const SizedBox(height: 10),
            if (topRates.isNotEmpty)
              Wrap(
                spacing: 8,
                children: topRates
                    .map((rate) => Chip(
                          label: Text("${(rate as num).toStringAsFixed(5)}%"),
                          backgroundColor: Colors.white,
                        ))
                    .toList(),
              )
            else
              const Text("시뮬레이션 데이터 없음"),
          ],
        ),
      ),
    );
  }

  Widget _buildBlueOceanCard(Map data) {
    final strategies = data['strategies'] as List? ?? [];
    return Card(
      elevation: 2,
      color: Colors.blue[50],
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          children: strategies.map((s) {
            final isBlue = s['type'] == 'Blue Ocean';
            return ListTile(
              leading: Icon(
                isBlue ? Icons.waves : Icons.warning,
                color: isBlue ? Colors.blue : Colors.red,
              ),
              title: Text(s['type']),
              subtitle: Text(s['reason']),
              trailing: Text(
                "${s['rate']}%",
                style: const TextStyle(fontWeight: FontWeight.bold),
              ),
            );
          }).toList(),
        ),
      ),
    );
  }

  Widget _buildCompetitionCard(Map data) {
    if (data.isEmpty) return const SizedBox();

    final count = data['predicted_count'] ?? 0;
    final difficulty = data['difficulty'] ?? "MEDIUM";
    final message = data['message'] ?? "";

    Color color;
    IconData icon;

    if (difficulty == "HIGH") {
      color = Colors.red;
      icon = Icons.local_fire_department_rounded;
    } else if (difficulty == "LOW") {
      color = Colors.blue;
      icon = Icons.pool_rounded;
    } else {
      color = Colors.orange;
      icon = Icons.balance_rounded;
    }

    return Card(
      elevation: 2,
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(icon, color: color, size: 28),
                const SizedBox(width: 8),
                Text(
                  difficulty == "HIGH"
                      ? "경쟁 매우 치열"
                      : (difficulty == "LOW" ? "경쟁 원활" : "경쟁 보통"),
                  style: TextStyle(
                      fontSize: 18, fontWeight: FontWeight.bold, color: color),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              "예상 참여 업체 수",
              style: TextStyle(color: Colors.grey[700], fontSize: 14),
            ),
            Text(
              "$count개사",
              style: const TextStyle(
                  fontSize: 32,
                  fontWeight: FontWeight.w800,
                  color: Colors.black87),
            ),
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              decoration: BoxDecoration(
                  color: Colors.grey[100],
                  borderRadius: BorderRadius.circular(8)),
              child: Text(
                message,
                style: TextStyle(fontSize: 13, color: Colors.grey[800]),
                textAlign: TextAlign.center,
              ),
            )
          ],
        ),
      ),
    );
  }
}
