#!/usr/bin/env bash
# create_project.sh
# Generates RCTimer.xcodeproj using the xcodeproj Ruby gem (ships with Xcode).
# Run once from the repo root: bash create_project.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "→ Checking for xcodeproj gem..."
if ! gem list xcodeproj -i &>/dev/null; then
    echo "  Installing xcodeproj gem (requires sudo if system Ruby)..."
    gem install xcodeproj --no-document
fi

echo "→ Generating RCTimer.xcodeproj..."
ruby - <<'RUBY'
require 'xcodeproj'

PROJECT_NAME = 'RCTimer'
BUNDLE_ID    = 'com.rctimer.app'

proj = Xcodeproj::Project.new("#{PROJECT_NAME}.xcodeproj")

# ── Main app target ──────────────────────────────────────────────────────────
target = proj.new_target(:application, PROJECT_NAME, :osx, '13.0')
target.product_name = PROJECT_NAME

# ── Source files group ────────────────────────────────────────────────────────
sources_group = proj.main_group.new_group(PROJECT_NAME, PROJECT_NAME)

swift_files = [
  "RCTimerApp.swift",
  "Models/Lap.swift",
  "Models/LapStore.swift",
  "Audio/AudioEngine.swift",
  "Camera/CameraManager.swift",
  "Camera/CameraView.swift",
  "Views/ContentView.swift",
  "Views/TimerDisplayView.swift",
  "Views/LapListView.swift",
  "Views/ControlBarView.swift",
  "Views/FlashOverlayView.swift",
  "Utilities/TimeFormatter.swift",
]

sources_phase = target.source_build_phase

swift_files.each do |rel_path|
  parts = rel_path.split('/')
  group = sources_group
  # Create sub-groups as needed
  parts[0..-2].each do |part|
    existing = group.children.find { |c| c.respond_to?(:name) && c.name == part }
    group = existing || group.new_group(part, part)
  end
  file_ref = group.new_file(rel_path)
  sources_phase.add_file_reference(file_ref)
end

# ── Resources ─────────────────────────────────────────────────────────────────
resources_group = sources_group.new_group('Resources', 'Resources')
plist_ref = resources_group.new_file('Resources/RCTimer-Info.plist')
# Info.plist is referenced via build settings, not added to resources phase

# ── Build settings ────────────────────────────────────────────────────────────
[target.debug_build_settings, target.release_build_settings].each do |s|
  s['PRODUCT_BUNDLE_IDENTIFIER']   = BUNDLE_ID
  s['SWIFT_VERSION']               = '5.9'
  s['MACOSX_DEPLOYMENT_TARGET']    = '13.0'
  s['INFOPLIST_FILE']              = "#{PROJECT_NAME}/Resources/RCTimer-Info.plist"
  s['CODE_SIGN_ENTITLEMENTS']      = "#{PROJECT_NAME}/RCTimer.entitlements"
  s['COMBINE_HIDPI_IMAGES']        = 'YES'
  s['ENABLE_HARDENED_RUNTIME']     = 'YES'
  s['SWIFT_OPTIMIZATION_LEVEL']    = '-Onone'
end

target.release_build_settings['SWIFT_OPTIMIZATION_LEVEL'] = '-O'

proj.save
puts "✓ #{PROJECT_NAME}.xcodeproj created successfully."
puts ""
puts "Next steps:"
puts "  1. open #{PROJECT_NAME}.xcodeproj"
puts "  2. Set your Team in Signing & Capabilities"
puts "  3. Build & Run (⌘R)"
RUBY
