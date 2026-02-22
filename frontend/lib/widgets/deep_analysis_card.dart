import 'package:flutter/material.dart';
import '../theme/style.dart';
import '../services/api_service.dart';
import '../models/deep_analysis.dart';

/// 첨부파일 심층 분석 카드
/// HWP/PDF 첨부파일을 AI로 분석하여 독소조항, 자격요건, 핵심 조건을 표시합니다.
class DeepAnalysisCard extends StatefulWidget {
  final String bidNo;

  const DeepAnalysisCard({super.key, required this.bidNo});

  @override
  State<DeepAnalysisCard> createState() => _DeepAnalysisCardState();
}

class _DeepAnalysisCardState extends State<DeepAnalysisCard> {
  final ApiService _apiService = ApiService();
  bool _isExpanded = false;
  Future<DeepAnalysis>? _analysisFuture;

  void _startAnalysis() {
    setState(() {
      _isExpanded = true;
      _analysisFuture = _apiService.fetchDeepAnalysis(widget.bidNo);
    });
  }

  @override
  Widget build(BuildContext context) {
    if (!_isExpanded) {
      return _buildTriggerButton();
    }

    return FutureBuilder<DeepAnalysis>(
      future: _analysisFuture,
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return _buildLoadingState();
        } else if (snapshot.hasError) {
          return _buildErrorState(snapshot.error.toString());
        } else if (!snapshot.hasData) {
          return const SizedBox.shrink();
        }

        final data = snapshot.data!;
        if (data.hasError) {
          return _buildErrorState(data.error!);
        }
        return _buildAnalysisContent(data);
      },
    );
  }

  Widget _buildTriggerButton() {
    return Container(
      width: double.infinity,
      decoration: BoxDecoration(
        color: AppColors.surfaceWhite,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.divider),
      ),
      child: Material(
        color: Colors.transparent,
        borderRadius: BorderRadius.circular(16),
        child: InkWell(
          borderRadius: BorderRadius.circular(16),
          onTap: _startAnalysis,
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Row(
              children: [
                Container(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(
                    color: Colors.deepPurple.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: const Icon(
                    Icons.description_outlined,
                    color: Colors.deepPurple,
                    size: 22,
                  ),
                ),
                const SizedBox(width: 14),
                const Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        "첨부파일 심층 분석",
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w600,
                          color: AppColors.textMain,
                        ),
                      ),
                      SizedBox(height: 2),
                      Text(
                        "규격서/특수조건의 독소조항을 AI가 분석해요",
                        style: TextStyle(
                          fontSize: 13,
                          color: AppColors.textSub,
                        ),
                      ),
                    ],
                  ),
                ),
                const Icon(
                  Icons.arrow_forward_ios_rounded,
                  size: 16,
                  color: AppColors.textSub,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildLoadingState() {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: AppColors.surfaceWhite,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        children: [
          const SizedBox(
            width: 48,
            height: 48,
            child: CircularProgressIndicator(
              strokeWidth: 3,
              valueColor:
                  AlwaysStoppedAnimation<Color>(Colors.deepPurple),
            ),
          ),
          const SizedBox(height: 16),
          const Text(
            "첨부파일을 분석하고 있어요",
            style: TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w600,
              color: AppColors.textMain,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            "파일 다운로드 및 AI 분석 중... 잠시 기다려주세요",
            style: TextStyle(
              fontSize: 13,
              color: AppColors.textSub.withOpacity(0.8),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildErrorState(String message) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: AppColors.surfaceWhite,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        children: [
          Icon(Icons.info_outline_rounded,
              size: 40, color: Colors.orange[400]),
          const SizedBox(height: 12),
          Text(
            message,
            textAlign: TextAlign.center,
            style: const TextStyle(
              fontSize: 14,
              color: AppColors.textSub,
            ),
          ),
          const SizedBox(height: 16),
          TextButton.icon(
            onPressed: _startAnalysis,
            icon: const Icon(Icons.refresh_rounded, size: 18),
            label: const Text("다시 시도"),
          ),
        ],
      ),
    );
  }

  Widget _buildAnalysisContent(DeepAnalysis data) {
    return Container(
      width: double.infinity,
      decoration: BoxDecoration(
        color: AppColors.surfaceWhite,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header with risk badge
          _buildHeader(data),
          const Divider(height: 1),

          Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Analyzed files
                if (data.analyzedFiles.isNotEmpty)
                  _buildAnalyzedFiles(data.analyzedFiles),

                // Qualification requirements
                if (data.qualificationRequirements.isNotEmpty) ...[
                  const SizedBox(height: 16),
                  _buildSection(
                    icon: Icons.verified_outlined,
                    title: "자격요건",
                    color: AppColors.primaryBlue,
                    child: _buildRequirements(data.qualificationRequirements),
                  ),
                ],

                // Toxic clauses
                if (data.toxicClauses.isNotEmpty) ...[
                  const SizedBox(height: 16),
                  _buildSection(
                    icon: Icons.warning_amber_rounded,
                    title: "독소조항",
                    color: AppColors.dangerRed,
                    child: _buildToxicClauses(data.toxicClauses),
                  ),
                ],

                // Key conditions
                if (data.keyConditions.isNotEmpty) ...[
                  const SizedBox(height: 16),
                  _buildSection(
                    icon: Icons.checklist_rounded,
                    title: "핵심 조건",
                    color: Colors.teal,
                    child: _buildKeyConditions(data.keyConditions),
                  ),
                ],

                // Summary
                if (data.summary.isNotEmpty) ...[
                  const SizedBox(height: 16),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: Colors.grey[50],
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          "종합 의견",
                          style: TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                            color: AppColors.textSub,
                          ),
                        ),
                        const SizedBox(height: 6),
                        Text(
                          data.summary,
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
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildHeader(DeepAnalysis data) {
    final riskColor = _riskColor(data.riskAssessment);
    final riskLabel = _riskLabel(data.riskAssessment);

    return Padding(
      padding: const EdgeInsets.all(20),
      child: Row(
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: Colors.deepPurple.withOpacity(0.1),
              borderRadius: BorderRadius.circular(10),
            ),
            child: const Icon(
              Icons.description_outlined,
              color: Colors.deepPurple,
              size: 20,
            ),
          ),
          const SizedBox(width: 12),
          const Expanded(
            child: Text(
              "첨부파일 심층 분석",
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: AppColors.textMain,
              ),
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
            decoration: BoxDecoration(
              color: riskColor.withOpacity(0.1),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Text(
              riskLabel,
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w700,
                color: riskColor,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAnalyzedFiles(List<String> files) {
    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: files.map((f) {
        return Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          decoration: BoxDecoration(
            color: Colors.grey[100],
            borderRadius: BorderRadius.circular(6),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.attach_file_rounded,
                  size: 14, color: Colors.grey[600]),
              const SizedBox(width: 4),
              Text(
                f,
                style: TextStyle(fontSize: 12, color: Colors.grey[700]),
              ),
            ],
          ),
        );
      }).toList(),
    );
  }

  Widget _buildSection({
    required IconData icon,
    required String title,
    required Color color,
    required Widget child,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, size: 18, color: color),
            const SizedBox(width: 6),
            Text(
              title,
              style: TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w700,
                color: color,
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        child,
      ],
    );
  }

  Widget _buildRequirements(List<QualificationRequirement> items) {
    return Column(
      children: items.map((item) {
        final isRequired = item.importance == '필수';
        return Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                margin: const EdgeInsets.only(top: 4),
                padding:
                    const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: isRequired
                      ? AppColors.dangerRed.withOpacity(0.1)
                      : Colors.grey[100],
                  borderRadius: BorderRadius.circular(4),
                ),
                child: Text(
                  item.importance,
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    color: isRequired ? AppColors.dangerRed : AppColors.textSub,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      item.category,
                      style: const TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                        color: AppColors.textSub,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      item.content,
                      style: const TextStyle(
                        fontSize: 14,
                        color: AppColors.textMain,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        );
      }).toList(),
    );
  }

  Widget _buildToxicClauses(List<ToxicClause> items) {
    return Column(
      children: items.map((item) {
        final severityColor = _riskColor(item.severity);
        return Container(
          margin: const EdgeInsets.only(bottom: 8),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: severityColor.withOpacity(0.04),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: severityColor.withOpacity(0.2)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: severityColor.withOpacity(0.1),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(
                      item.severity,
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                        color: severityColor,
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Text(
                    item.type,
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppColors.textMain,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Text(
                item.content,
                style: const TextStyle(
                  fontSize: 14,
                  color: AppColors.textMain,
                  height: 1.4,
                ),
              ),
              if (item.recommendation != null) ...[
                const SizedBox(height: 6),
                Text(
                  "→ ${item.recommendation}",
                  style: TextStyle(
                    fontSize: 13,
                    color: Colors.blue[700],
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ],
            ],
          ),
        );
      }).toList(),
    );
  }

  Widget _buildKeyConditions(List<KeyCondition> items) {
    return Column(
      children: items.map((item) {
        return Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                margin: const EdgeInsets.only(top: 2),
                width: 6,
                height: 6,
                decoration: const BoxDecoration(
                  color: Colors.teal,
                  shape: BoxShape.circle,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      "${item.category}: ${item.content}",
                      style: const TextStyle(
                        fontSize: 14,
                        color: AppColors.textMain,
                      ),
                    ),
                    if (item.note != null)
                      Text(
                        item.note!,
                        style: const TextStyle(
                          fontSize: 12,
                          color: AppColors.textSub,
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
        );
      }).toList(),
    );
  }

  Color _riskColor(String level) {
    switch (level) {
      case 'HIGH':
        return AppColors.dangerRed;
      case 'MEDIUM':
        return Colors.orange;
      case 'LOW':
        return AppColors.safeGreen;
      default:
        return AppColors.textSub;
    }
  }

  String _riskLabel(String level) {
    switch (level) {
      case 'HIGH':
        return "위험 높음";
      case 'MEDIUM':
        return "주의 필요";
      case 'LOW':
        return "안전";
      default:
        return level;
    }
  }
}
