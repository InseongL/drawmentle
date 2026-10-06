"""Sketch classifiers with 345 raw logits (docs/model-architecture-v1.md §5).

No softmax or calibration inside the network: the browser runtime applies softmax(logits / T) over all outputs.
The Conv1D + BiLSTM comparison model needs a stroke-sequence dataset and is added with it.
"""
from __future__ import annotations

import torch
from torch import nn
from torchvision.models import mobilenet_v3_small

NUM_CLASSES = 345


class SmallCNN(nn.Module):
    """A: connectivity and regression check. 1xHxW -> 32 -> 64 -> 128 -> global average pool -> Linear."""

    def __init__(self, num_classes: int = NUM_CLASSES):
        super().__init__()

        def block(cin, cout, pool):
            layers = [nn.Conv2d(cin, cout, 3, padding=1, bias=False), nn.BatchNorm2d(cout), nn.ReLU(inplace=True)]
            return layers + ([nn.MaxPool2d(2)] if pool else [])

        self.features = nn.Sequential(*block(1, 32, True), *block(32, 64, True), *block(64, 128, False))
        self.head = nn.Linear(128, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.features(x).mean(dim=(2, 3)))


def mobilenet_v3_small_1ch(num_classes: int = NUM_CLASSES, stem_stride: int = 2) -> nn.Module:
    """B: torchvision MobileNetV3-Small, trained from scratch, with a single-channel stem.

    stem_stride=1 keeps 2x more resolution through the network (4x compute) for small 64px inputs.
    """
    model = mobilenet_v3_small(weights=None, num_classes=num_classes)
    old = model.features[0][0]
    model.features[0][0] = nn.Conv2d(1, old.out_channels, old.kernel_size, stride=stem_stride,
                                     padding=old.padding, bias=False)
    return model


def build(name: str, **kwargs) -> nn.Module:
    if name == "small_cnn":
        return SmallCNN(kwargs.get("num_classes", NUM_CLASSES))
    if name == "mobilenet_v3_small":
        return mobilenet_v3_small_1ch(kwargs.get("num_classes", NUM_CLASSES), kwargs.get("stem_stride", 2))
    raise ValueError(f"unknown model {name!r}")
