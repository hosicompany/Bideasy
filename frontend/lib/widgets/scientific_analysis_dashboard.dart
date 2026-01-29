import 'package:flutter/material.dart';
import '../services/api_service.dart';

class ScientificAnalysisDashboard extends StatefulWidget {
  final String bidNo;

  const ScientificAnalysisDashboard({Key? key, required this.bidNo})
      : super(key: key);

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
      return Center(child: CircularProgressIndicator());
    }

    if (_error != null) {
      return Center(child: Text("분석 실패: $_error"));
    }

    if (_analysisData == null) {
      return Center(child: Text("데이터가 없습니다."));
    }

    final agency = _analysisData!['agency_profile'] ?? {};
    final monteCarlo = _analysisData!['monte_carlo'] ?? {};
    final blueOcean = _analysisData!['blue_ocean'] ?? {};

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildSectionHeader("📊 1. 발주처 성향 분석 (Agency Profiling)"),
        _buildAgencyCard(agency),
        SizedBox(height: 20),
        _buildSectionHeader("🎰 2. 몬테카를로 시뮬레이션 (확률 1등)"),
        _buildMonteCarloCard(monteCarlo),
        SizedBox(height: 20),
        _buildSectionHeader("🔵 3. 블루오션 전략 (경쟁 회피)"),
        _buildBlueOceanCard(blueOcean),
      ],
    );
  }

  Widget _buildSectionHeader(String title) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8.0),
      child: Text(
        title,
        style: TextStyle(
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
              Text(data['message'], style: TextStyle(color: Colors.grey))
            else ...[
              Text("이 발주처의 과거 낙찰 평균 사정률",
                  style: TextStyle(fontSize: 14, color: Colors.grey[700])),
              SizedBox(height: 8),
              Text(
                "${data['avg_rate']}%",
                style: TextStyle(
                    fontSize: 32,
                    fontWeight: FontWeight.bold,
                    color: Colors.black),
              ),
              Text("표본수: ${data['sample_size']}건",
                  style: TextStyle(color: Colors.grey)),
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
            Text(data['description'] ?? "", style: TextStyle(fontSize: 14)),
            SizedBox(height: 10),
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
              Text("시뮬레이션 데이터 없음"),
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
                style: TextStyle(fontWeight: FontWeight.bold),
              ),
            );
          }).toList(),
        ),
      ),
    );
  }
}
