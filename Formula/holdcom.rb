# Homebrew formula for holdcom.
#
# holdcom is a standalone, pure-stdlib Python script (no pip / no compilation).
#
# Install locally (from this repo) without a tap:
#   brew install --formula Formula/holdcom.rb
#
# Or, once published in a tap (e.g. generalquin1991/homebrew-tap):
#   brew tap generalquin1991/tap
#   brew install holdcom
#
# BEFORE PUBLISHING: replace the placeholder sha256 with the real digest of
# the release tarball (available after `git push origin v0.1.1`):
#   curl -fsSL https://github.com/generalquin1991/holdcom/archive/refs/tags/v0.1.1.tar.gz | sha256sum

class Holdcom < Formula
  desc "On-demand serial take-over without resetting the MCU (picocom-like)"
  homepage "https://github.com/generalquin1991/holdcom"
  url "https://github.com/generalquin1991/holdcom/archive/refs/tags/v0.1.1.tar.gz"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000" # TODO: replace
  version "0.1.1"
  license "MIT"

  depends_on "python@3.13"

  def install
    # The tarball extracts to holdcom-<version>/; grab the script regardless of
    # the exact directory name. Wrap it so it runs with the brewed python.
    libexec.install Dir["holdcom-*/holdcom.py"].first
    (bin/"holdcom").write_exec_script libexec/"holdcom.py"
  end

  test do
    assert_match "usage: holdcom", shell_output("#{bin}/holdcom --help")
  end
end
