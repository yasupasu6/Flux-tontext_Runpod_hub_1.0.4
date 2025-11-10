# RunPodサーバーレスデプロイ時の503エラー修正ガイド

## 問題の概要

Dockerイメージのプッシュ中に`registry.runpod.net`でCloudflareの503エラー（エラーコード1105）が発生しています。

### エラーの詳細

```
[ERROR] Retry: layer 31/35 f214164ad6bc left=7 error=patch failed layer=sha256:f214164ad6bc38dbb422de236b11475bbf5e1ab7c31ae96d6aa0454e8f761260 chunkIndex=40 contentRange=4000000000-4099999999 url=https://registry.runpod.net/v2/... status=503
```

エラーメッセージには「Temporarily unavailable」と表示され、Cloudflareのエラーページが返されています。

### 主な原因

1. **イメージサイズが大きすぎる**: 約30.88GBのイメージサイズ
2. **レイヤーサイズの問題**: Layer 31が6.99GBと非常に大きい
3. **レジストリの制限**: RunPodレジストリへの大きなレイヤーのアップロード時にタイムアウトや制限に達している
4. **ネットワークの問題**: 大きなファイルの転送中にネットワークタイムアウトが発生

## 修正方法

### 1. Dockerfileの最適化

#### 1.1 レイヤーの統合と順序の最適化

**問題点**: 現在のDockerfileでは複数のRUNコマンドが別々のレイヤーとして作成されており、レイヤー数が多くなっています。

**解決策**: 関連するRUNコマンドを統合してレイヤー数を削減します。

**最適化前**:
```dockerfile
RUN pip install -U "huggingface_hub[hf_transfer]"
RUN pip install runpod websocket-client librosa
```

**最適化後**:
```dockerfile
RUN pip install --no-cache-dir -U "huggingface_hub[hf_transfer]" && \
    pip install --no-cache-dir runpod websocket-client librosa && \
    rm -rf /root/.cache/pip
```

#### 1.2 不要なファイルの削除

**問題点**: ビルド中に作成されたキャッシュや一時ファイルがイメージに残っています。

**解決策**: 各RUNコマンドの最後でキャッシュと一時ファイルを削除します。

- aptキャッシュの削除（既に実施済み）
- pipキャッシュの削除
- git履歴の削除（ComfyUIやComfyUI-Managerの.gitディレクトリ）
- 一時ファイルの削除

#### 1.3 .dockerignoreファイルの追加

**問題点**: ビルドコンテキストに不要なファイルが含まれています。

**解決策**: `.dockerignore`ファイルを作成して、以下のファイルを除外します：

- ドキュメントファイル（*.md）
- 例示ファイル（example_image.png、flux_kontext_example.json）
- Git関連ファイル（.git、.gitignore）
- Pythonキャッシュ（__pycache__、*.pyc）
- IDE設定ファイル（.vscode、.idea）

### 2. ビルド戦略の改善

#### 2.1 マルチステージビルドの活用

**推奨事項**: 現在のDockerfileは既にマルチステージビルドを使用していますが、さらに最適化できます。

- ビルドステージとランタイムステージを明確に分離
- ビルド依存関係（git、wgetなど）を最終イメージに含めない（可能な場合）

#### 2.2 モデルファイルの最適化

**問題点**: モデルファイル（約6-7GB）がDockerイメージに含まれているため、イメージサイズが大きくなっています。

**解決策**: 

1. **Network Volumeの活用（推奨）**
   - モデルファイルをNetwork Volumeに配置
   - コンテナ起動時にモデルファイルをダウンロードまたはマウント
   - これによりDockerイメージサイズを大幅に削減できます

2. **entrypoint.shでのダウンロード**
   - モデルファイルのダウンロードをDockerfileからentrypoint.shに移動
   - 初回起動時にダウンロード（キャッシュ可能）

### 3. リトライ戦略

#### 3.1 手動リトライ

**手順**:

1. RunPodダッシュボードにログイン
2. 該当のServerless Endpointを選択
3. 「Rebuild」または「Build」ボタンをクリック
4. ネットワークが安定している時間帯（深夜や早朝）に再試行

#### 3.2 段階的なデプロイ

**手順**:

1. まず小さなベースイメージでビルドをテスト
2. モデルファイルを除いた状態でビルドを確認
3. 段階的にコンポーネントを追加して問題を特定

### 4. その他の最適化手法

#### 4.1 レイヤー順序の最適化

**原則**: 
- 頻繁に変更されないレイヤーを先に配置
- 頻繁に変更されるレイヤー（COPY . .など）を最後に配置
- これにより、変更時の再ビルド時間を短縮できます

#### 4.2 並列ダウンロードの最適化

**問題点**: モデルファイルのダウンロードが順次実行されています。

**解決策**: 可能な限り並列ダウンロードを実行（ただし、ディスクI/Oの制限に注意）

## 実装例

### 最適化されたDockerfileの例

```dockerfile
# Use specific version of nvidia cuda image
FROM wlsdml1114/multitalk-base:1.7 as runtime

# Install system dependencies and Python packages in a single layer
RUN apt-get update && \
    apt-get install -y wget && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir -U "huggingface_hub[hf_transfer]" && \
    pip install --no-cache-dir runpod websocket-client librosa && \
    rm -rf /root/.cache/pip

# Set working directory
WORKDIR /

# Clone ComfyUI and install dependencies in a single layer
RUN git clone https://github.com/comfyanonymous/ComfyUI.git && \
    cd ComfyUI && \
    pip install --no-cache-dir -r requirements.txt && \
    rm -rf /root/.cache/pip && \
    cd /ComfyUI/custom_nodes/ && \
    git clone https://github.com/ltdrdata/ComfyUI-Manager.git && \
    cd ComfyUI-Manager && \
    pip install --no-cache-dir -r requirements.txt && \
    rm -rf /root/.cache/pip && \
    rm -rf /ComfyUI/.git && \
    rm -rf /ComfyUI/custom_nodes/ComfyUI-Manager/.git

# Download models in a single layer (consider moving to entrypoint.sh)
RUN hf download Comfy-Org/flux1-kontext-dev_ComfyUI split_files/diffusion_models/flux1-dev-kontext_fp8_scaled.safetensors --local-dir /ComfyUI/models/unet/ && \
    hf download comfyanonymous/flux_text_encoders clip_l.safetensors --local-dir=/ComfyUI/models/clip/ && \
    hf download comfyanonymous/flux_text_encoders t5xxl_fp16.safetensors --local-dir=/ComfyUI/models/clip/ && \
    wget -q https://huggingface.co/Comfy-Org/Lumina_Image_2.0_Repackaged/resolve/main/split_files/vae/ae.safetensors -O /ComfyUI/models/vae/ae.safetensors

# Copy application files (this should be last as it changes frequently)
COPY . .
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
```

## トラブルシューティング

### エラーが継続する場合

1. **RunPodサポートへの連絡**
   - RunPodのサポートチームに連絡して、レジストリの制限や問題を確認
   - エラーログとRay IDを提供

2. **代替レジストリの使用**
   - Docker Hubや他のレジストリにプッシュしてから、RunPodにインポート（RunPodがサポートしている場合）

3. **イメージサイズの確認**
   ```bash
   docker images
   ```
   イメージサイズが30GBを超えている場合は、さらなる最適化が必要です

### ビルド時間の短縮

- Docker BuildKitのキャッシュを活用
- 頻繁に変更されないレイヤーのキャッシュを保持
- ローカルでビルドしてからプッシュ（可能な場合）

## 注意事項

- イメージサイズを削減することで、デプロイ時間とコストを削減できます
- モデルファイルが大きい場合は、Network Volumeの使用を強く推奨します
- ビルドが失敗した場合は、RunPodのサポートに連絡することを推奨します
- ネットワークが不安定な場合は、再試行する前にしばらく待機してください

## 参考リンク

- [RunPod Documentation](https://docs.runpod.io/)
- [Docker Best Practices](https://docs.docker.com/develop/dev-best-practices/)
- [Dockerfile Best Practices](https://docs.docker.com/develop/dev-best-practices/dockerfile_best-practices/)

