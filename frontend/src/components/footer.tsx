import { Github, Mail, Heart } from "lucide-react";

export function Footer() {
  return (
    <footer className="w-full border-t border-border/50 bg-muted/30">
      <div className="container mx-auto px-4 py-8">
        <div className="flex flex-col md:flex-row items-center justify-between gap-4">
          {/* 版权信息 */}
          <div className="text-sm text-muted-foreground">
            <p>© 2024 简聘. All rights reserved.</p>
          </div>

          {/* 链接 */}
          <div className="flex items-center gap-6">
            <a
              href="#"
              className="text-sm text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1"
            >
              <Github className="w-4 h-4" />
              GitHub
            </a>
            <a
              href="#"
              className="text-sm text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1"
            >
              <Mail className="w-4 h-4" />
              联系我们
            </a>
          </div>

          {/* 制作信息 */}
          <div className="text-sm text-muted-foreground flex items-center gap-1">
            Made with <Heart className="w-4 h-4 text-[var(--danger)] fill-current" /> by AI
          </div>
        </div>
      </div>
    </footer>
  );
}
