{
  description = "Agent-native control plane for external skill catalogs";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = {
    self,
    nixpkgs,
  }: let
    systems = [
      "aarch64-darwin"
      "aarch64-linux"
      "x86_64-linux"
    ];
    forAllSystems = nixpkgs.lib.genAttrs systems;
  in {
    packages = forAllSystems (system: let
      pkgs = nixpkgs.legacyPackages.${system};
    in {
      default = pkgs.python3Packages.buildPythonApplication {
        pname = "musterctl";
        version = "0.1.2";
        src = self;
        pyproject = true;
        build-system = [pkgs.python3Packages.hatchling];
        pythonImportsCheck = ["musterctl"];
        meta.mainProgram = "musterctl";
      };
    });

    apps = forAllSystems (system: {
      default = {
        type = "app";
        program = "${self.packages.${system}.default}/bin/musterctl";
      };
    });

    checks = forAllSystems (system: {
      package = self.packages.${system}.default;
    });

    formatter = forAllSystems (
      system: nixpkgs.legacyPackages.${system}.alejandra
    );
  };
}
