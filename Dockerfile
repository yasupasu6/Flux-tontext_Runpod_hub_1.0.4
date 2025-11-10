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

# Download models in a single layer
# Note: Consider moving model downloads to entrypoint.sh or using Network Volumes
# to reduce Docker image size further
RUN hf download Comfy-Org/flux1-kontext-dev_ComfyUI split_files/diffusion_models/flux1-dev-kontext_fp8_scaled.safetensors --local-dir /ComfyUI/models/unet/ && \
    hf download comfyanonymous/flux_text_encoders clip_l.safetensors --local-dir=/ComfyUI/models/clip/ && \
    hf download comfyanonymous/flux_text_encoders t5xxl_fp16.safetensors --local-dir=/ComfyUI/models/clip/ && \
    wget -q https://huggingface.co/Comfy-Org/Lumina_Image_2.0_Repackaged/resolve/main/split_files/vae/ae.safetensors -O /ComfyUI/models/vae/ae.safetensors

# Copy application files (this should be last as it changes frequently)
COPY . .
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]