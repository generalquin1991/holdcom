# Homebrew formula for holdcom.
#
# holdcom is a standalone, pure-stdlib Python script (no pip / no compilation).
#
# Install locally (from this repo) without a tap:
#   brew install --formula Formula/holdcom.rb
#
# Or, once published in a tap (e.g. yourname/homebrew-tap):
#   brew tap yourname/tap
#   brew install holdcom
#
# BEFORE PUBLISHING — replace the following:
#   - generalquin1991 with your GitHub account
#   - the placeholder sha256 with the real digest of the raw file:
#       curl -fsSL <url> | sha256sum
#   - tag a release v0.1.0 so the URL resolves
#   - choose a license and add a LICENSE file, then uncomment the license line

class Holdcom < Formula
  desc "On-demand serial take-over without resetting the MCU (picocom-like)"
  homepage "https://github.com/generalquin1991/holdcom"
  url "https://raw.githubusercontent.com/generalquin1991/holdcom/v0.1.0/holdcom.py"
  sha256 "f26d27e64ea4b82c434234e7ab01116d3b860cc3afe0b307e9ad30319ad42d23"
  version "0.1.0"
  license "MIT"

  depends_on "python@3.13"

  def install
    # holdcom.py ships with "#!/usr/bin/env python3"; wrap it so it runs with
    # the brewed python and keeps the original file untouched under libexec.
    libexec.install "holdcom.py"
    (bin/"holdcom").write_exec_script libexec/"holdcom.py"
  end

  test do
    assert_match "usage: holdcom", shell_output("#{bin}/holdcom --help")
  end
end
