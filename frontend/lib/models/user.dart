class User {
  final int id;
  final String? email;
  final String? companyName;
  final String? ceoName;
  final String? licenses; // Comma-separated
  final String? location;
  final int? capacityCost;
  final int? performanceRecord;
  final int points;

  User({
    required this.id,
    this.email,
    this.companyName,
    this.ceoName,
    this.licenses,
    this.location,
    this.capacityCost,
    this.performanceRecord,
    required this.points,
  });

  factory User.fromJson(Map<String, dynamic> json) {
    return User(
      id: json['id'],
      email: json['email'],
      companyName: json['company_name'],
      ceoName: json['ceo_name'],
      licenses: json['licenses'],
      location: json['location'],
      capacityCost: json['capacity_cost'],
      performanceRecord: json['performance_record'],
      points: json['points'] ?? 0,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'company_name': companyName,
      'ceo_name': ceoName,
      'licenses': licenses,
      'location': location,
      'capacity_cost': capacityCost,
      'performance_record': performanceRecord,
    };
  }
}
