import Foundation

struct Lap: Identifiable, Equatable {
    let id: UUID
    let number: Int
    let duration: TimeInterval  // seconds
    let timestamp: Date

    init(number: Int, duration: TimeInterval) {
        self.id = UUID()
        self.number = number
        self.duration = duration
        self.timestamp = Date()
    }
}
