# Homebrew cask for claude-usage-bar
#
# To add to Homebrew:
#   brew tap your-org/tools https://github.com/your-org/homebrew-tools
#   brew install --cask claude-usage-bar
#
# SHA256 and URL are updated automatically by the GitHub Actions release pipeline.

cask "claude-usage-bar" do
  version "0.1.0"
  sha256 "REPLACE_WITH_DMG_SHA256"

  url "https://github.com/REPLACE_ORG/claude-usage-bar/releases/download/v#{version}/claude-usage-bar-#{version}.dmg"

  name "Claude Usage Bar"
  desc "macOS menu bar app showing real-time Claude token usage and cost"
  homepage "https://github.com/REPLACE_ORG/claude-usage-bar"

  # Minimum macOS version — limited by rumps AppKit requirement
  depends_on macos: ">= :ventura"

  app "Claude Usage Bar.app"

  # Install LaunchAgent so the app auto-starts on login
  postflight do
    system_command "#{appdir}/Claude Usage Bar.app/Contents/MacOS/claude-usage-bar",
                   args:         ["install"],
                   sudo:         false,
                   print_stderr: false
  end

  uninstall_preflight do
    system_command "#{appdir}/Claude Usage Bar.app/Contents/MacOS/claude-usage-bar",
                   args:         ["uninstall"],
                   sudo:         false,
                   print_stderr: false
  end

  # Full cleanup on `brew uninstall --zap`
  zap trash: [
    "~/.claude-usage-bar",
    "~/Library/LaunchAgents/com.claude-usage-bar.plist",
    "~/Library/Logs/claude-usage-bar",
  ]
end
