import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../models/opening_result.dart';
import '../models/notice.dart';
import '../services/api_service.dart';
import '../theme/style.dart';

class OpeningResultTable extends StatefulWidget {
  final Notice notice;

  const OpeningResultTable({super.key, required this.notice});

  @override
  State<OpeningResultTable> createState() => _OpeningResultTableState();
}

class _OpeningResultTableState extends State<OpeningResultTable> {
  final ApiService _apiService = ApiService();
  late Future<List<OpeningResult>> _futureResults;

  @override
  void initState() {
    super.initState();
    _futureResults = _apiService.fetchOpeningResults(widget.notice.bidNo);
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<OpeningResult>>(
      future: _futureResults,
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        } else if (snapshot.hasError) {
          return Center(
              child: Text("결과 정보를 불러오지 못했습니다.\n${snapshot.error}",
                  textAlign: TextAlign.center));
        } else if (!snapshot.hasData || snapshot.data!.isEmpty) {
          return const Center(
              child: Text("개찰 결과가 아직 없습니다.",
                  style: TextStyle(color: Colors.grey)));
        }

        final results = snapshot.data!;

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text("개찰 순위", style: AppTextStyles.h2),
            const SizedBox(height: 12),
            Container(
              decoration: BoxDecoration(
                border: Border.all(color: AppColors.divider),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                children: [
                  // Header
                  Container(
                    padding:
                        const EdgeInsets.symmetric(vertical: 8, horizontal: 8),
                    decoration: BoxDecoration(
                      color: AppColors.backgroundGrey,
                      borderRadius:
                          const BorderRadius.vertical(top: Radius.circular(8)),
                    ),
                    child: Row(
                      children: const [
                        SizedBox(
                            width: 40,
                            child: Text("순위",
                                style: TextStyle(
                                    fontWeight: FontWeight.bold, fontSize: 12),
                                textAlign: TextAlign.center)),
                        Expanded(
                            flex: 3,
                            child: Text("업체명",
                                style: TextStyle(
                                    fontWeight: FontWeight.bold,
                                    fontSize: 12))),
                        Expanded(
                            flex: 2,
                            child: Text("대표자",
                                style: TextStyle(
                                    fontWeight: FontWeight.bold,
                                    fontSize: 12))),
                        Expanded(
                            flex: 3,
                            child: Text("투찰금액",
                                style: TextStyle(
                                    fontWeight: FontWeight.bold, fontSize: 12),
                                textAlign: TextAlign.right)),
                        SizedBox(width: 8),
                      ],
                    ),
                  ),
                  const Divider(height: 1, color: AppColors.divider),
                  // List
                  ListView.separated(
                    shrinkWrap: true,
                    physics: const NeverScrollableScrollPhysics(),
                    itemCount: results.length,
                    separatorBuilder: (c, i) =>
                        const Divider(height: 1, color: AppColors.divider),
                    itemBuilder: (context, index) {
                      final item = results[index];
                      final isWinner = index == 0;
                      return Container(
                        color: isWinner
                            ? AppColors.primaryBlue.withOpacity(0.05)
                            : Colors.white,
                        padding: const EdgeInsets.symmetric(
                            vertical: 12, horizontal: 8),
                        child: Row(
                          children: [
                            SizedBox(
                                width: 40,
                                child: Text("${item.rank}",
                                    style: TextStyle(
                                        fontWeight: FontWeight.bold,
                                        color: isWinner
                                            ? AppColors.primaryBlue
                                            : Colors.black),
                                    textAlign: TextAlign.center)),
                            Expanded(
                                flex: 3,
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(item.company,
                                        style: const TextStyle(
                                            fontSize: 13,
                                            fontWeight: FontWeight.w500),
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis),
                                    if (item.successState.isNotEmpty &&
                                        item.successState != "정상")
                                      Text(item.successState,
                                          style: const TextStyle(
                                              fontSize: 11, color: Colors.red)),
                                  ],
                                )),
                            Expanded(
                                flex: 2,
                                child: Text(item.ceo,
                                    style: const TextStyle(fontSize: 12),
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis)),
                            Expanded(
                                flex: 3,
                                child: Text(
                                    "${NumberFormat('#,###').format(item.bidPrice)}원",
                                    style: const TextStyle(
                                        fontSize: 13, fontFamily: "Monospace"),
                                    textAlign: TextAlign.right)),
                            const SizedBox(width: 8),
                          ],
                        ),
                      );
                    },
                  ),
                ],
              ),
            ),
          ],
        );
      },
    );
  }
}
