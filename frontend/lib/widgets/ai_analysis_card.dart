import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../theme/style.dart';
import '../services/api_service.dart';
import '../models/ai_analysis.dart';
import '../models/notice.dart';

class AiAnalysisCard extends StatefulWidget {
  final Notice notice;

  const AiAnalysisCard({
    super.key,
    required this.notice,
  });

  @override
  State<AiAnalysisCard> createState() => _AiAnalysisCardState();
}

class _AiAnalysisCardState extends State<AiAnalysisCard> {
  final ApiService _apiService = ApiService();
  late Future<AiAnalysis> _analysisFuture;

  @override
  void initState() {
    super.initState();
    _analysisFuture = _apiService.fetchBidAnalysis(
      widget.notice.bidNo,
      widget.notice.toAnalysisParams(),
    );
  }

  Future<void> _launchURL() async {
    final Uri url = Uri.parse(widget.notice.content);
    if (!await launchUrl(url, mode: LaunchMode.externalApplication)) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('원문 링크를 열 수 없습니다.')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<AiAnalysis>(
      future: _analysisFuture,
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        } else if (snapshot.hasError) {
          return Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: AppColors.backgroundGrey,
              borderRadius: BorderRadius.circular(16),
            ),
            child: const Text("분석을 불러오지 못했습니다. (서버 연결 확인 필요)"),
          );
        } else if (!snapshot.hasData) {
          return const SizedBox.shrink();
        }

        final data = snapshot.data!;
        return Container(
          width: double.infinity,
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: const Color(0xFFF9FAFB),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: const Color(0xFFE5E8EB)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 1. Header
              const Row(
                children: [
                  Icon(Icons.auto_awesome,
                      size: 18, color: AppColors.primaryBlue),
                  SizedBox(width: 6),
                  Text(
                    "AI 입찰 분석",
                    style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                      color: AppColors.primaryBlue,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),

              // 2. Badges (Carousel or Wrap)
              if (data.badges.isNotEmpty)
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: data.badges.map((badge) {
                    return Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 10, vertical: 6),
                      decoration: BoxDecoration(
                        color: AppColors.primaryBlue.withOpacity(0.1),
                        borderRadius: BorderRadius.circular(20),
                        border:
                            Border.all(color: AppColors.primaryBlue, width: 1),
                      ),
                      child: Text(
                        badge,
                        style: const TextStyle(
                          color: AppColors.primaryBlue,
                          fontWeight: FontWeight.w600,
                          fontSize: 12,
                        ),
                      ),
                    );
                  }).toList(),
                ),
              if (data.badges.isNotEmpty) const SizedBox(height: 20),

              // 3. Status Checks
              ...data.checkItems.map((item) => Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Icon(
                          item.status == 'OK'
                              ? Icons.check_circle_rounded
                              : Icons.error_rounded,
                          color: item.status == 'OK'
                              ? Colors.green
                              : AppColors.dangerRed,
                          size: 20,
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: RichText(
                            text: TextSpan(
                              style: const TextStyle(
                                  color: AppColors.textMain, fontSize: 14),
                              children: [
                                TextSpan(
                                  text: "${item.label} : ",
                                  style: const TextStyle(
                                      fontWeight: FontWeight.bold),
                                ),
                                TextSpan(
                                  text: item.text,
                                  style: const TextStyle(height: 1.4),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ],
                    ),
                  )),

              // 4. Tips
              if (data.tips.isNotEmpty) ...[
                const SizedBox(height: 16),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.grey[100],
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        "💡 알아두세요",
                        style: TextStyle(
                          fontWeight: FontWeight.w700,
                          fontSize: 13,
                          color: AppColors.textSub,
                        ),
                      ),
                      const SizedBox(height: 8),
                      ...data.tips.map(
                        (tip) => Padding(
                          padding: const EdgeInsets.only(bottom: 4),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Text("• ",
                                  style: TextStyle(
                                      color: AppColors.textSub, height: 1.4)),
                              Expanded(
                                child: Text(
                                  tip,
                                  style: const TextStyle(
                                    fontSize: 13,
                                    color: AppColors.textMain,
                                    height: 1.4,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ],

              // 5. View Original Button
              const SizedBox(height: 20),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: _launchURL,
                      style: OutlinedButton.styleFrom(
                        side: const BorderSide(color: Color(0xFFE5E8EB)),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12),
                        ),
                        padding: const EdgeInsets.symmetric(vertical: 14),
                      ),
                      child: const Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(Icons.description_outlined,
                              size: 18, color: AppColors.textSub),
                          SizedBox(width: 8),
                          Text(
                            "원문 보기",
                            style: TextStyle(
                              color: AppColors.textMain,
                              fontWeight: FontWeight.w600,
                              fontSize: 14,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                  if (widget.notice.attachmentUrl != null &&
                      widget.notice.attachmentUrl!.isNotEmpty) ...[
                    const SizedBox(width: 12),
                    Expanded(
                      child: ElevatedButton(
                        onPressed: () async {
                          final Uri url =
                              Uri.parse(widget.notice.attachmentUrl!);
                          if (!await launchUrl(url,
                              mode: LaunchMode.externalApplication)) {
                            if (mounted) {
                              ScaffoldMessenger.of(context).showSnackBar(
                                const SnackBar(
                                    content: Text('첨부파일을 열 수 없습니다.')),
                              );
                            }
                          }
                        },
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppColors.primaryBlue,
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(12),
                          ),
                          padding: const EdgeInsets.symmetric(vertical: 14),
                          elevation: 0,
                        ),
                        child: const Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(Icons.attachment_rounded,
                                size: 18, color: Colors.white),
                            SizedBox(width: 8),
                            Text(
                              "규격서 보기",
                              style: TextStyle(
                                color: Colors.white,
                                fontWeight: FontWeight.w600,
                                fontSize: 14,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ],
          ),
        );
      },
    );
  }
}
