import 'package:intl/intl.dart';

class Notice {
  // Core fields
  final String bidNo;
  final String title;
  final String content; // Notice URL
  final double basicPrice;
  final double? basisAmount;
  final String basisStatus;
  final DateTime? basisAmountAt;
  final double? lowerLimitRate;
  final String? lowerLimitSource;
  final double? prdprcRangeBgn;
  final double? prdprcRangeEnd;
  final DateTime? startDate;
  final DateTime? endDate;
  final String? contractType;
  final String? organization;

  // Extended fields for AI analysis
  final String? demandOrganization;
  final String? bidMethod;
  final String? contractMethod;
  final String? bidType;
  final String? status;
  final String? region;
  final double? budgetAmount;
  final DateTime? openingDate;
  final String? internationalBid;
  final String? jointContract;
  final String? bigCompanyOk;
  final String? smeOnly;
  final String? bidQualification;
  final String? emergencyBid;
  final String? rebidYn;
  final String? attachmentUrl;
  final String? attachmentName;

  // Calculated fields (populated by AI Analysis or Calculator)
  final int? aValue;
  final String? aValueSource;
  final String? aValueApplicable;
  final int? netCost;

  Notice({
    required this.bidNo,
    required this.title,
    required this.content,
    required this.basicPrice,
    this.basisAmount,
    this.basisStatus = 'unconfirmed',
    this.basisAmountAt,
    this.lowerLimitRate,
    this.lowerLimitSource,
    this.prdprcRangeBgn,
    this.prdprcRangeEnd,
    this.startDate,
    this.endDate,
    this.contractType,
    this.organization,
    this.demandOrganization,
    this.bidMethod,
    this.contractMethod,
    this.bidType,
    this.status,
    this.region,
    this.budgetAmount,
    this.openingDate,
    this.internationalBid,
    this.jointContract,
    this.bigCompanyOk,
    this.smeOnly,
    this.bidQualification,
    this.emergencyBid,
    this.rebidYn,
    this.attachmentUrl,
    this.attachmentName,
    this.aValue,
    this.aValueSource,
    this.aValueApplicable,
    this.netCost,
  });

  double? get confirmedBasisAmount {
    final amount = basisAmount;
    if (basisStatus.toLowerCase() != 'confirmed' ||
        amount == null ||
        amount <= 0) {
      return null;
    }
    return amount;
  }

  bool get isConstruction {
    final normalized = (contractType ?? '').trim().toUpperCase();
    return normalized == 'CONSTRUCTION' ||
        normalized == 'WORKS' ||
        normalized == '공사' ||
        (bidType ?? '').contains('공사');
  }

  bool get isClosed {
    if (openingDate == null) return false;
    return DateTime.now().isAfter(openingDate!);
  }

  // Factory for JSON parsing with extended fields
  factory Notice.fromJson(Map<String, dynamic> json) {
    DateTime? parseDate(String? dateStr) {
      if (dateStr == null || dateStr.isEmpty) return null;
      try {
        // Handle "YYYY-MM-DD HH:mm:ss" typical in DB
        return DateTime.parse(dateStr.replaceAll(' ', 'T'));
      } catch (e) {
        return null;
      }
    }

    double? parseDouble(Object? value) {
      if (value is num) return value.toDouble();
      return double.tryParse(value?.toString() ?? '');
    }

    int? parseInt(Object? value) {
      if (value is num) return value.toInt();
      return int.tryParse(value?.toString() ?? '');
    }

    final parsedBasisAmount = parseDouble(json['basis_amount']);

    return Notice(
      // Core fields
      bidNo: json['bid_no'] ?? '',
      title: json['title'] ?? '',
      basicPrice: (json['basic_price'] ?? 0).toDouble(),
      basisAmount: parsedBasisAmount,
      // An amount without an explicit confirmation status is not sufficient
      // evidence for a safety calculation; the screen will fetch context.
      basisStatus: json['basis_status']?.toString() ?? 'unconfirmed',
      basisAmountAt: parseDate(json['basis_amount_at']?.toString()),
      lowerLimitRate: parseDouble(json['lower_limit_rate']),
      lowerLimitSource: json['lower_limit_source']?.toString(),
      prdprcRangeBgn: parseDouble(json['prdprc_range_bgn']),
      prdprcRangeEnd: parseDouble(json['prdprc_range_end']),
      contractType: json['contract_type'],
      content: json['content'] ?? '',
      startDate: parseDate(json['start_date']),
      endDate: parseDate(json['end_date']),
      organization: json['organization'],

      // Extended fields
      demandOrganization: json['demand_organization'],
      bidMethod: json['bid_method'],
      contractMethod: json['contract_method'],
      bidType: json['bid_type'],
      status: json['status'],
      region: json['region'],
      budgetAmount: json['budget_amount'] != null
          ? (json['budget_amount']).toDouble()
          : null,
      openingDate: parseDate(json['opening_date']),
      internationalBid: json['international_bid'],
      jointContract: json['joint_contract'],
      bigCompanyOk: json['big_company_ok'],
      smeOnly: json['sme_only'],
      bidQualification: json['bid_qualification'],
      emergencyBid: json['emergency_bid'],
      rebidYn: json['rebid_yn'],
      attachmentUrl: json['attachment_url'],
      attachmentName: json['attachment_name'],
      aValue: parseInt(json['a_value']),
      aValueSource: json['a_value_source']?.toString(),
      aValueApplicable: json['a_value_applicable']?.toString(),
      netCost: parseInt(json['net_cost']),
    );
  }

  /// Merge the authoritative calculation fields returned by `/bids/{id}/context`.
  /// Missing context values never turn the estimated price into a basis amount.
  Notice withCalculationContext(Map<String, dynamic> json) {
    double? parseDouble(Object? value) {
      if (value is num) return value.toDouble();
      return double.tryParse(value?.toString() ?? '');
    }

    int? parseInt(Object? value) {
      if (value is num) return value.toInt();
      return int.tryParse(value?.toString() ?? '');
    }

    DateTime? parseDate(Object? value) {
      final raw = value?.toString();
      if (raw == null || raw.isEmpty) return null;
      return DateTime.tryParse(raw.replaceAll(' ', 'T'));
    }

    return copyWith(
      basisAmount: parseDouble(json['basis_amount']),
      basisStatus: json['basis_status']?.toString(),
      basisAmountAt: parseDate(json['basis_amount_at']),
      startDate: parseDate(json['bid_date']),
      lowerLimitRate: parseDouble(json['lower_limit_rate']),
      lowerLimitSource: json['lower_limit_source']?.toString(),
      prdprcRangeBgn: parseDouble(json['prdprc_range_bgn']),
      prdprcRangeEnd: parseDouble(json['prdprc_range_end']),
      contractType: json['contract_type']?.toString(),
      bidMethod: json['bid_method']?.toString(),
      contractMethod: json['contract_method']?.toString(),
      aValue: parseInt(json['a_value']),
      aValueSource: json['a_value_source']?.toString(),
      aValueApplicable: json['a_value_applicable']?.toString(),
      netCost: parseInt(json['net_cost']),
    );
  }

  // Formatting helper
  String get formattedPrice {
    final formatter = NumberFormat('#,###');
    return formatter.format(basicPrice.toInt());
  }

  // Convert to query params for AI API
  Map<String, String> toAnalysisParams() {
    final params = <String, String>{};
    if (title.isNotEmpty) params['title'] = title;
    // Notice.basicPrice is presmptPrce (estimated price), not the confirmed
    // basis used by safety calculations.
    if (basicPrice > 0) params['estimated_price'] = basicPrice.toString();
    final basis = confirmedBasisAmount;
    if (basis != null) {
      params['basis_amount'] = basis.toString();
      params['basis_status'] = 'confirmed';
    }
    if (lowerLimitRate != null) {
      params['lower_limit_rate'] = lowerLimitRate.toString();
    }
    if (prdprcRangeBgn != null) {
      params['prdprc_range_bgn'] = prdprcRangeBgn.toString();
    }
    if (prdprcRangeEnd != null) {
      params['prdprc_range_end'] = prdprcRangeEnd.toString();
    }
    if (aValue != null) params['a_value'] = aValue.toString();
    if (aValueSource != null) params['a_value_source'] = aValueSource!;
    if (aValueApplicable != null) {
      params['a_value_applicable'] = aValueApplicable!;
    }
    if (organization != null) params['organization'] = organization!;
    if (demandOrganization != null) {
      params['demand_organization'] = demandOrganization!;
    }
    if (bidMethod != null) params['bid_method'] = bidMethod!;
    if (contractMethod != null) params['contract_method'] = contractMethod!;
    if (contractType != null) params['contract_type'] = contractType!;
    if (bidType != null) params['bid_type'] = bidType!;
    if (status != null) params['status'] = status!;
    if (region != null) params['region'] = region!;
    if (budgetAmount != null) params['budget_amount'] = budgetAmount.toString();
    if (openingDate != null) {
      params['opening_date'] = openingDate!.toIso8601String(); // Use ISO format
    }
    if (internationalBid != null) {
      params['international_bid'] = internationalBid!;
    }
    if (jointContract != null) params['joint_contract'] = jointContract!;
    if (bigCompanyOk != null) params['big_company_ok'] = bigCompanyOk!;
    if (smeOnly != null) params['sme_only'] = smeOnly!;
    if (emergencyBid != null) params['emergency_bid'] = emergencyBid!;
    if (rebidYn != null) params['rebid_yn'] = rebidYn!;
    if (attachmentUrl != null) params['attachment_url'] = attachmentUrl!;
    if (attachmentName != null) params['attachment_name'] = attachmentName!;
    if (startDate != null) params['start_date'] = startDate!.toIso8601String();
    if (endDate != null) params['end_date'] = endDate!.toIso8601String();
    if (content.isNotEmpty) params['notice_url'] = content;
    return params;
  }

  Notice copyWith({
    String? bidNo,
    String? title,
    String? content,
    double? basicPrice,
    double? basisAmount,
    String? basisStatus,
    DateTime? basisAmountAt,
    double? lowerLimitRate,
    String? lowerLimitSource,
    double? prdprcRangeBgn,
    double? prdprcRangeEnd,
    DateTime? startDate,
    DateTime? endDate,
    String? contractType,
    String? organization,
    String? demandOrganization,
    String? bidMethod,
    String? contractMethod,
    String? bidType,
    String? status,
    String? region,
    double? budgetAmount,
    DateTime? openingDate,
    String? internationalBid,
    String? jointContract,
    String? bigCompanyOk,
    String? smeOnly,
    String? bidQualification,
    String? emergencyBid,
    String? rebidYn,
    String? attachmentUrl,
    String? attachmentName,
    int? aValue,
    String? aValueSource,
    String? aValueApplicable,
    int? netCost,
  }) {
    return Notice(
      bidNo: bidNo ?? this.bidNo,
      title: title ?? this.title,
      content: content ?? this.content,
      basicPrice: basicPrice ?? this.basicPrice,
      basisAmount: basisAmount ?? this.basisAmount,
      basisStatus: basisStatus ?? this.basisStatus,
      basisAmountAt: basisAmountAt ?? this.basisAmountAt,
      lowerLimitRate: lowerLimitRate ?? this.lowerLimitRate,
      lowerLimitSource: lowerLimitSource ?? this.lowerLimitSource,
      prdprcRangeBgn: prdprcRangeBgn ?? this.prdprcRangeBgn,
      prdprcRangeEnd: prdprcRangeEnd ?? this.prdprcRangeEnd,
      startDate: startDate ?? this.startDate,
      endDate: endDate ?? this.endDate,
      contractType: contractType ?? this.contractType,
      organization: organization ?? this.organization,
      demandOrganization: demandOrganization ?? this.demandOrganization,
      bidMethod: bidMethod ?? this.bidMethod,
      contractMethod: contractMethod ?? this.contractMethod,
      bidType: bidType ?? this.bidType,
      status: status ?? this.status,
      region: region ?? this.region,
      budgetAmount: budgetAmount ?? this.budgetAmount,
      openingDate: openingDate ?? this.openingDate,
      internationalBid: internationalBid ?? this.internationalBid,
      jointContract: jointContract ?? this.jointContract,
      bigCompanyOk: bigCompanyOk ?? this.bigCompanyOk,
      smeOnly: smeOnly ?? this.smeOnly,
      bidQualification: bidQualification ?? this.bidQualification,
      emergencyBid: emergencyBid ?? this.emergencyBid,
      rebidYn: rebidYn ?? this.rebidYn,
      attachmentUrl: attachmentUrl ?? this.attachmentUrl,
      attachmentName: attachmentName ?? this.attachmentName,
      aValue: aValue ?? this.aValue,
      aValueSource: aValueSource ?? this.aValueSource,
      aValueApplicable: aValueApplicable ?? this.aValueApplicable,
      netCost: netCost ?? this.netCost,
    );
  }
}
