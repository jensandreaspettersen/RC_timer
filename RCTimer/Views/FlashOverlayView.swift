import SwiftUI
import Combine

struct FlashOverlayView: View {
    @EnvironmentObject var lapStore: LapStore
    @State private var isFlashing = false
    @State private var cancellable: AnyCancellable?

    var body: some View {
        Color.white
            .opacity(isFlashing ? 0.35 : 0)
            .ignoresSafeArea()
            .allowsHitTesting(false)
            .onAppear {
                cancellable = lapStore.lapRecorded
                    .receive(on: RunLoop.main)
                    .sink { [self] _ in
                        withAnimation(.easeIn(duration: 0.05)) {
                            isFlashing = true
                        }
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
                            withAnimation(.easeOut(duration: 0.2)) {
                                isFlashing = false
                            }
                        }
                    }
            }
    }
}
