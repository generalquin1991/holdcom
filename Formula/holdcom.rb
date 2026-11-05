# Homebrew formula for holdcom.
#
# holdcom is a standalone, PURE-STDLIB Python script: it imports nothing
# outside the Python standard library, so it needs no pip packages and no
# dedicated Python interpreter. Its shebang is `#!/usr/bin/env python3`,
# which means it runs with WHATEVER python3 is already on PATH — the
# macOS-built-in /usr/bin/python3, a Homebrew python, or a user-installed
# one. We therefore declare NO `depends_on "python"` and just install the
# script as-is. This keeps the install tiny and lets the OS-provided Python
# be used (the user asked for exactly this).
#
# Install locally (from this repo) via a tap:
#   brew tap-new generalquin1991/tap
#   cp Formula/holdcom.rb "$(brew --repo generalquin1991/tap)/Formula/"
#   brew trust generalquin1991/tap
#   brew install holdcom
#
# Or, once published in a public tap:
#   brew tap generalquin1991/tap
#   brew install holdcom
#
# The tarball's sha256 below is the real digest of the v0.1.1 release
# archive (curl -fsSL <tarball-url> | sha256sum).

class Holdcom < Formula
  desc "On-demand serial take-over without resetting the MCU (picocom-like)"
  homepage "https://github.com/generalquin1991/holdcom"
  url "https://github.com/generalquin1991/holdcom/archive/refs/tags/v0.1.7.tar.gz"
  sha256 "d526c1e97d655a42c85cdd24d028ef9bb3dac619b45484af5fcf38ab35d8e70c"
  version "0.1.7"
  license "MIT"

  # No `depends_on "python"`: the script is pure stdlib and uses the
  # system / any python3 already on PATH via its `#!/usr/bin/env python3`
  # shebang. Declaring a python dependency would only pull a redundant
  # interpreter.

  def install
    # The GitHub tarball extracts to holdcom-<version>/ (the cwd during
    # install), so holdcom.py sits directly here. Install it as bin/holdcom,
    # preserving the env-python3 shebang.
    bin.install "holdcom.py" => "holdcom"
  end

  test do
    assert_match "usage: holdcom", shell_output("#{bin}/holdcom --help")
    assert_match "holdcom 0.1.7", shell_output("#{bin}/holdcom --version")
  end
end
