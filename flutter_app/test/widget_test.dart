import 'package:flutter_test/flutter_test.dart';
import 'package:yalla_go/main.dart';

void main() {
  testWidgets('YallaGo app starts', (WidgetTester tester) async {
    await tester.pumpWidget(const YallaGoApp());

    expect(find.text('YallaGo'), findsOneWidget);
  });
}