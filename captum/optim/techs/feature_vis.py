# %load_ext autoreload
# %autoreload 2

from typing import Dict, Callable, Iterable

from tqdm.auto import tqdm

import torch
import torch.nn as nn
import torch.optim as optim

from kornia.losses import total_variation

from lucid.misc.io import save
from clarity.pytorch.io import show
from clarity.pytorch.models import googlenet
from clarity.pytorch.param import (
    NaturalImage,
    RandomAffine,
    GaussianSmoothing,
    BlendAlpha,
    IgnoreAlpha,
)
from clarity.pytorch.optim.objectives import (
    InputOptimization,
    single_target_objective,
    channel_activation,
    neuron_activation,
)
from clarity.pytorch.optim.optimize import optimize, n_steps

if torch.cuda.is_available():
    device = torch.device("cuda:0")
else:
    device = torch.device("cpu")


def alpha_neuron(target, param, channel_index):
    def innr(mapping):
        acts = mapping[target]
        input_value = mapping[param]
        _, _, H, W = acts.shape
        obj = acts[:, channel_index, H // 2, W // 2]
        mean_alpha = input_value[3].mean()
        # mean_tv = total_variation(input_value[3:])
        return obj * (1 - mean_alpha)  # - mean_tv

    return innr


def run():
    net = googlenet(pretrained=True).to(device)

    robustness_transforms = nn.Sequential(
        RandomAffine(translate=True, rotate=True),
        BlendAlpha(),
    )

    param = NaturalImage((112, 112), channels=4).to(device)

    target = net.mixed3a._1x1
    objective = InputOptimization(
        net=net,
        input_param=param,
        transform=robustness_transforms,
        targets=[target, param],
        loss_function=alpha_neuron(target, param, channel_index=8),
    )

    optimize(objective, n_steps(128))
    result = objective.input_param()
    save(result.detach().numpy().transpose(1, 2, 0), "image.png")
    return result.cpu()


def example_of_two_stage_optimization():
    # TODO: Objective abstraction doesn't work that well. Should just be nn.Module??
    # TODO: loss functions don't yet compose, thus "alpha_neuron"; dirty as it is
    # TODO: eliminate having to pass targets twice: once to objective as targets, once to loss function. Should be one abstraction? Sketch first!

    net = googlenet(pretrained=True).to(device)
    param = NaturalImage((112, 112), channels=4).to(device)
    target = net.mixed3a._3x3[-1]
    channel_index = 76 - 64

    ignore_transforms = nn.Sequential(
        RandomAffine(translate=True, rotate=True), IgnoreAlpha()
    )
    objective = InputOptimization(
        net=net,
        input_param=param,
        transform=ignore_transforms,
        targets=[target],
        loss_function=neuron_activation(target, channel_index=channel_index),
    )

    optimize(objective, n_steps(256))

    intermediate_result = param()
    show(intermediate_result)

    blend_transforms = nn.Sequential(
        RandomAffine(translate=True, rotate=True), BlendAlpha()
    )
    objective.transform = blend_transforms
    objective.targets = [target, param]
    objective.loss_function = alpha_neuron(target, param, channel_index=channel_index)

    optimize(objective, n_steps(512))

    final_result = param()
    show(final_result)

    return intermediate_result, final_result


if __name__ == "__main__":
    example_of_two_stage_optimization()
