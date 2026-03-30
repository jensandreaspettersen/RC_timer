import SwiftUI

struct ContentView: View {
    @EnvironmentObject var lapStore: LapStore
    @EnvironmentObject var audioEngine: AudioEngine
    @StateObject private var cameraManager = CameraManager()

    var body: some View {
        ZStack {
            // Layer 0: live camera feed
            CameraView(session: cameraManager.session)
                .ignoresSafeArea()

            // Layer 1: dim overlay
            Color.black.opacity(0.70)
                .ignoresSafeArea()

            // Layer 2: HUD
            VStack(spacing: 16) {
                TimerDisplayView()
                LapListView()
                Spacer()
                ControlBarView()
            }

            // Layer 3: lap flash
            FlashOverlayView()
        }
        .preferredColorScheme(.dark)
        .frame(minWidth: 520, minHeight: 480)
        .onAppear {
            cameraManager.configure()
            cameraManager.start()
            audioEngine.onClickDetected = { [weak lapStore] in
                lapStore?.recordLap()
            }
            try? audioEngine.start()
        }
        .onDisappear {
            cameraManager.stop()
            audioEngine.stop()
        }
    }
}
