import SwiftUI

@main
struct RCTimerApp: App {
    @StateObject private var lapStore = LapStore()
    @StateObject private var audioEngine = AudioEngine()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(lapStore)
                .environmentObject(audioEngine)
        }
        .windowStyle(.hiddenTitleBar)
        .windowResizability(.contentMinSize)
        .commands {
            CommandGroup(replacing: .newItem) {}
        }
    }
}
