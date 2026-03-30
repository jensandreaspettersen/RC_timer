import Foundation
import Combine

enum RaceState {
    case idle
    case running
}

@MainActor
final class LapStore: ObservableObject {
    @Published var state: RaceState = .idle
    @Published var currentElapsed: TimeInterval = 0
    @Published var laps: [Lap] = []

    let lapRecorded = PassthroughSubject<Void, Never>()

    private var lapStart: Date = .now
    private var raceStart: Date = .now
    private var timerCancellable: AnyCancellable?

    var bestLap: Lap? {
        laps.min(by: { $0.duration < $1.duration })
    }

    func start() {
        guard state == .idle else { return }
        raceStart = Date()
        lapStart = raceStart
        currentElapsed = 0
        state = .running
        timerCancellable = Timer.publish(every: 0.01, on: .main, in: .common)
            .autoconnect()
            .sink { [weak self] _ in
                guard let self else { return }
                self.currentElapsed = Date().timeIntervalSince(self.lapStart)
            }
    }

    func reset() {
        timerCancellable = nil
        state = .idle
        currentElapsed = 0
        laps = []
    }

    func recordLap() {
        guard state == .running else { return }
        let now = Date()
        let lapDuration = now.timeIntervalSince(lapStart)
        let lap = Lap(number: laps.count + 1, duration: lapDuration)
        laps.append(lap)
        lapStart = now
        currentElapsed = 0
        lapRecorded.send()
    }
}
