import { cn } from "@/lib/utils";
import { Upload, FileText, X } from "lucide-react";
import { useCallback, useState } from "react";

interface FileUploadProps {
  accept?: string;
  maxSize?: number; // in MB
  onFileSelect?: (file: File) => void;
  onFileRemove?: () => void;
  className?: string;
  disabled?: boolean;
}

export function FileUpload({
  // 第 15 步：与后端契约对齐 —— 后端只实现了 .pdf / .docx（python-docx 不支持老的 .doc 二进制格式），
  // 这里不再放行 .doc，避免"前端能选、后端 400"的错配。
  accept = ".pdf,.docx",
  maxSize = 5,
  onFileSelect,
  onFileRemove,
  className,
  disabled = false,
}: FileUploadProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  const validateFile = (file: File): boolean => {
    setError(null);

    // Check file size
    if (file.size > maxSize * 1024 * 1024) {
      setError(`文件大小超过 ${maxSize}MB 限制`);
      return false;
    }

    // Check file type（与后端 upload.py 支持的后缀保持一致）
    const validTypes = [
      "application/pdf",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ];
    if (!validTypes.includes(file.type)) {
      const isLegacyDoc =
        file.type === "application/msword" || file.name.toLowerCase().endsWith(".doc");
      setError(
        isLegacyDoc
          ? "不支持旧版 .doc 格式，请用 Word「另存为 .docx」后重新上传"
          : "仅支持 PDF 或 DOCX 文件",
      );
      return false;
    }

    return true;
  };

  const handleFile = useCallback(
    (file: File) => {
      if (validateFile(file)) {
        setSelectedFile(file);
        onFileSelect?.(file);
      }
    },
    [onFileSelect]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      if (disabled) return;

      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [disabled, handleFile]
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    if (!disabled) setIsDragging(true);
  }, [disabled]);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  const handleRemove = useCallback(() => {
    setSelectedFile(null);
    setError(null);
    onFileRemove?.();
  }, [onFileRemove]);

  if (selectedFile) {
    return (
      <div
        className={cn(
          "flex items-center gap-3 p-4 rounded-xl border bg-card",
          className
        )}
      >
        <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-primary/10 text-primary">
          <FileText className="w-5 h-5" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium truncate">{selectedFile.name}</p>
          <p className="text-xs text-muted-foreground">
            {(selectedFile.size / 1024 / 1024).toFixed(2)} MB
          </p>
        </div>
        <button
          onClick={handleRemove}
          className="p-2 rounded-lg hover:bg-muted transition-colors"
          disabled={disabled}
        >
          <X className="w-4 h-4 text-muted-foreground" />
        </button>
      </div>
    );
  }

  return (
    <div className={className}>
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        className={cn(
          "relative flex flex-col items-center justify-center gap-3 p-8 rounded-xl border-2 border-dashed transition-all duration-200",
          isDragging
            ? "border-primary bg-primary/5 scale-[1.02]"
            : "border-border bg-muted/30 hover:border-primary/50 hover:bg-muted/50",
          disabled && "opacity-50 cursor-not-allowed"
        )}
      >
        <input
          type="file"
          accept={accept}
          onChange={handleInputChange}
          disabled={disabled}
          className="absolute inset-0 w-full h-full opacity-0 cursor-pointer disabled:cursor-not-allowed"
        />
        <div
          className={cn(
            "flex items-center justify-center w-12 h-12 rounded-full bg-primary/10 text-primary transition-transform duration-200",
            isDragging && "scale-110"
          )}
        >
          <Upload className="w-6 h-6" />
        </div>
        <div className="text-center">
          <p className="text-sm font-medium text-foreground">
            点击或拖拽上传文件
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            支持 PDF、DOCX 格式，最大 {maxSize}MB
          </p>
        </div>
      </div>
      {error && (
        <p className="mt-2 text-sm text-destructive text-center">{error}</p>
      )}
    </div>
  );
}
