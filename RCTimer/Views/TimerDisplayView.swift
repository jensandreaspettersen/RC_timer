import SwiftUI

struct TimerDisplayView: View {
    @EnvironmentObject var lapStore: LapStore

    var body: some View {
        Text(TimeFormatter.format(lapStore.currentElapsed))
            .font(.custom("Impact", size: 96))
            .monospacedDigit()
            .foregroundColor(.white)
            .shadow(color: .black.opacity(0.8), radius: 4, x: 2, y: 2)
            .padding(.top, 24)
    }
}
