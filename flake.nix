{
  description = "dehydrater：把课堂录像和课件脱水成逐字稿、通知清单和讲义";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { nixpkgs, ... }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [ pkgs.python313 pkgs.uv ];
          env = {
            UV_PYTHON = "${pkgs.python313}/bin/python";
            UV_PYTHON_DOWNLOADS = "never";
          }
          // pkgs.lib.optionalAttrs pkgs.stdenv.isLinux {
            # PyPI 上的 manylinux wheel（PyAV、PyMuPDF、numpy）运行时需要这些动态库
            LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib pkgs.zlib ];
          };
        };
      });
    };
}
