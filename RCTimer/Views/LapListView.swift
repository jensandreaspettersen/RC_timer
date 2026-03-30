import SwiftUI

struct LapListView: View {
    @EnvironmentObject var lapStore: LapStore

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 6) {
                ForEach(lapStore.laps.reversed()) { lap in
                    LapRowView(lap: lap, isBest: lap == lapStore.bestLap)
                }
            }
            .padding(.horizontal, 24)
        }
        .frame(maxHeight: 220)
    }
}

struct LapRowView: View {
    let lap: Lap
    let isBest: Bool

    private let gold = Color(red: 1.0, green: 0.843, blue: 0.0)

    var body: some View {
        HStack {
            Text("LAP \(lap.number)")
                .font(.system(size: 14, weight: .semibold, design: .monospaced))
                .foregroundColor(isBest ? gold : .gray)
                .frame(width: 70, alignment: .leading)

            Text(TimeFormatter.format(lap.duration))
                .font(.custom("Impact", size: 28))
                .monospacedDigit()
                .foregroundColor(isBest ? gold : .white)

            Spacer()

            if isBest {
                Text("★ BEST")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundColor(gold)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(gold.opacity(0.15))
                    .cornerRadius(6)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(Color.white.opacity(isBest ? 0.08 : 0.05))
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(isBest ? gold.opacity(0.6) : Color.clear, lineWidth: 1)
                )
        )
    }
}
