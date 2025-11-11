import { Github, ExternalLink } from "lucide-react";

export function Footer() {
  return (
    <footer className="bg-white border-t border-gray-200 mt-auto py-8 sm:py-12">
      <div className="w-full px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-12 items-center">

          {/* Funding Logos */}
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-6 sm:gap-8">
              {/* BMWSB Logo */}
              <div className="flex-shrink-0">
                <img
                  src="/assets/bmwsb-logo.png"
                  alt="Bundesministerium für Wohnen, Stadtentwicklung und Bauwesen"
                  className="h-20 sm:h-24 lg:h-32 w-auto object-contain"
                />
              </div>

              {/* KfW Logo */}
              <div className="flex-shrink-0">
                <img
                  src="/assets/KFW-Logo.png"
                  alt="KfW Kreditanstalt für Wiederaufbau"
                  className="h-16 sm:h-20 lg:h-24 w-auto object-contain"
                />
              </div>

              {/* Stadt Kassel Logo */}
              <div className="flex-shrink-0">
                <img
                  src="/assets/Logo-Stadt-Kassel.png"
                  alt="Stadt Kassel"
                  className="h-12 sm:h-14 lg:h-16 w-auto object-contain"
                />
              </div>
            </div>
          </div>

          {/* Center Separator */}
          <div className="hidden lg:flex justify-center">
            <div className="w-px h-24 bg-gray-200"></div>
          </div>
          <div className="lg:hidden">
            <div className="h-px bg-gray-200 my-4"></div>
          </div>

          {/* Links and Project Info */}
          <div className="space-y-6">
            {/* Project Links */}
            <div>
              <h3 className="text-sm font-semibold text-text mb-3">Projekt</h3>
              <div className="space-y-2">
                <a
                  href="https://github.com/smart-village-solutions/smart-speech-flow-backend"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 text-sm text-primary hover:text-primary-dark transition-colors"
                >
                  <Github className="w-4 h-4" />
                  <span>GitHub Repository</span>
                  <ExternalLink className="w-3 h-3" />
                </a>
              </div>
            </div>

            {/* Legal Links */}
            <div>
              <h3 className="text-sm font-semibold text-text mb-3">Rechtliches</h3>
              <div className="space-y-2">
                <a
                  href="https://www.kassel.de/datenschutzerklaerung.php"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 text-sm text-gray-600 hover:text-primary transition-colors"
                >
                  <span>Datenschutzerklärung</span>
                  <ExternalLink className="w-3 h-3" />
                </a>
                <a
                  href="https://www.kassel.de/impressum.php"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 text-sm text-gray-600 hover:text-primary transition-colors"
                >
                  <span>Impressum</span>
                  <ExternalLink className="w-3 h-3" />
                </a>
              </div>
            </div>

            {/* Copyright */}
            <div className="pt-4 border-t border-gray-100">
              <p className="text-xs text-gray-500">
                © {new Date().getFullYear()} Stadt Kassel - Smart Speech Flow
              </p>
            </div>
          </div>
        </div>
      </div>
    </footer>
  );
}
