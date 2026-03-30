import AVFoundation
import Combine

final class AudioEngine: ObservableObject {
    @Published var currentRMS: Float = 0
    @Published var sensitivity: Float = 0.15

    var onClickDetected: (() -> Void)?

    private let engine = AVAudioEngine()
    private var lastTriggerTime: Date = .distantPast
    private let debounceInterval: TimeInterval = 1.0
    private var isRunning = false

    func start() throws {
        guard !isRunning else { return }

        let inputNode = engine.inputNode
        let format = inputNode.inputFormat(forBus: 0)

        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
            self?.processSamples(buffer)
        }

        try engine.start()
        isRunning = true
    }

    func stop() {
        guard isRunning else { return }
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        isRunning = false
    }

    private func processSamples(_ buffer: AVAudioPCMBuffer) {
        guard let channelData = buffer.floatChannelData?[0] else { return }
        let frameCount = Int(buffer.frameLength)
        guard frameCount > 0 else { return }

        var sumOfSquares: Float = 0
        for i in 0..<frameCount {
            sumOfSquares += channelData[i] * channelData[i]
        }
        let rms = sqrt(sumOfSquares / Float(frameCount))

        DispatchQueue.main.async { [weak self] in
            self?.currentRMS = rms
        }

        let threshold = sensitivity
        guard rms > threshold else { return }

        let now = Date()
        guard now.timeIntervalSince(lastTriggerTime) > debounceInterval else { return }
        lastTriggerTime = now

        DispatchQueue.main.async { [weak self] in
            self?.onClickDetected?()
        }
    }
}
