import SwiftUI

struct ControlBarView: View {
    @EnvironmentObject var lapStore: LapStore
    @EnvironmentObject var audioEngine: AudioEngine

    var body: some View {
        VStack(spacing: 12) {
            // Buttons row
            HStack(spacing: 16) {
                RaceButton(title: "START", color: Color(red: 0.75, green: 0.22, blue: 0.17)) {
                    lapStore.start()
                }
                .disabled(lapStore.state == .running)
                .opacity(lapStore.state == .running ? 0.4 : 1.0)

                RaceButton(title: "RESET", color: Color(white: 0.25)) {
                    lapStore.reset()
                }
            }

            // Sensitivity row
            HStack(spacing: 10) {
                Image(systemName: "mic.fill")
                    .foregroundColor(.gray)
                    .font(.system(size: 13))

                Slider(value: $audioEngine.sensitivity, in: 0.01...0.5)
                    .tint(Color(red: 0.75, green: 0.22, blue: 0.17))
                    .frame(width: 160)

                Text(String(format: "%.2f", audioEngine.currentRMS))
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundColor(audioEngine.currentRMS > audioEngine.sensitivity ? .green : .gray)
                    .frame(width: 38, alignment: .leading)
            }
        }
        .padding(.bottom, 24)
    }
}

struct RaceButton: View {
    let title: String
    let color: Color
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.custom("Impact", size: 22))
                .foregroundColor(.white)
                .frame(width: 120, height: 44)
                .background(
                    RoundedRectangle(cornerRadius: 8)
                        .fill(color)
                )
        }
        .buttonStyle(.plain)
    }
}
