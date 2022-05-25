import torch
import numpy as np

from core.config import BaseConfig
from core.utils import make_procgen, WarpFrame, EpisodicLifeEnv
from core.dataset import Transforms
from .env_wrapper import ProcgenWrapper
from .model import EfficientZeroNet



class ProcgenConfig(BaseConfig):
    def __init__(self):
        super(ProcgenConfig, self).__init__(
            training_steps=300000,
            last_steps=0,
            test_interval=20000,  # in training steps
            log_interval=1000,
            vis_interval=1000,
            test_episodes=300,
            checkpoint_interval=100,
            target_model_interval=200,
            save_ckpt_interval=100000,
            max_moves=4000,
            test_max_moves=4000,
            history_length=400,
            discount=0.997,
            dirichlet_alpha=0.3,
            value_delta_max=0.01,
            num_simulations=50,
            batch_size=256,
            td_steps=5,
            num_actors=1,
            # network initialization/ & normalization
            episode_life=True,
            init_zero=True,
            clip_reward=True,
            # storage efficient
            cvt_string=True,
            image_based=True,
            # lr scheduler
            use_adam=False,
            lr_warm_up=0.01,
            lr_init=0.2,
            lr_decay_rate=0.1,
            lr_decay_steps=100000,
            auto_td_steps_ratio=0.3,
            # replay window
            start_transitions=8,
            total_transitions=100 * 1000,  # not used by the replay buffer ? TODO 100*10000
            transition_num=1.0,  # size of the replay buffer in millions of env steps ? TODO 0.5
            # frame skip & stack observation
            frame_skip=1,
            stacked_observations=4,
            # coefficient
            reward_loss_coeff=1,
            value_loss_coeff=0.25,
            policy_loss_coeff=1,
            consistency_coeff=2,
            # reward sum
            lstm_hidden_size=512,
            lstm_horizon_len=5,
            # siamese
            proj_hid=1024,
            proj_out=1024,
            pred_hid=512,
            pred_out=1024,)

        self.num_levels_per_env = 500  # will be updated in set_config function
        self.bn_mt = 0.1
        self.blocks = 1  # Number of blocks in the ResNet
        self.channels = 64  # Number of channels in the ResNet
        if self.gray_scale:
            self.channels = 32
        self.reduced_channels_reward = 16  # x36 Number of channels in reward head
        self.reduced_channels_value = 16  # x36 Number of channels in value head
        self.reduced_channels_policy = 16  # x36 Number of channels in policy head
        self.resnet_fc_reward_layers = [32]  # Define the hidden layers in the reward head of the dynamic network
        self.resnet_fc_value_layers = [32]  # Define the hidden layers in the value head of the prediction network
        self.resnet_fc_policy_layers = [32]  # Define the hidden layers in the policy head of the prediction network
        self.downsample = True  # Downsample observations before representation network (See paper appendix Network Architecture)

    def visit_softmax_temperature_fn(self, num_moves, trained_steps):
        if self.change_temperature:
            if trained_steps < 0.5 * (self.training_steps + self.last_steps):
                return 1.0
            elif trained_steps < 0.75 * (self.training_steps + self.last_steps):
                return 0.5
            else:
                return 0.25
        else:
            return 1.0

    def set_config(self, args):
        exp_path = super(ProcgenConfig, self).set_config(args)
        self.channels = args.channels
        self.blocks = args.blocks
        # set procgen related params
        # 500 distinct training levels in procgen, which we evenly distribute across environments
        num_parallel_envs = self.num_actors * self.p_mcts_num
        self.num_levels_per_env = int(np.ceil(500 / num_parallel_envs))
        print(f"training on {self.num_levels_per_env * num_parallel_envs}")
        return exp_path

    def set_game(self, env_name, save_video=False, save_path=None, video_callable=None):
        self.env_name = env_name
        # gray scale
        if self.gray_scale:
            self.image_channel = 1
        obs_shape = (self.image_channel, 64, 64)
        self.obs_shape = (obs_shape[0] * self.stacked_observations, obs_shape[1], obs_shape[2])

        game = self.new_game(seed=0)
        self.action_space_size = game.action_space_size

    def get_uniform_network(self):
        return EfficientZeroNet(
            self.obs_shape,
            self.action_space_size,
            self.blocks,
            self.channels,
            self.reduced_channels_reward,
            self.reduced_channels_value,
            self.reduced_channels_policy,
            self.resnet_fc_reward_layers,
            self.resnet_fc_value_layers,
            self.resnet_fc_policy_layers,
            self.reward_support.size,
            self.value_support.size,
            self.downsample,
            self.inverse_value_transform,
            self.inverse_reward_transform,
            self.lstm_hidden_size,
            bn_mt=self.bn_mt,
            proj_hid=self.proj_hid,
            proj_out=self.proj_out,
            pred_hid=self.pred_hid,
            pred_out=self.pred_out,
            init_zero=self.init_zero,
            state_norm=self.state_norm)

    def new_game(self, seed=None, save_video=False, save_path=None, video_callable=None, uid=None, test=False, final_test=False):

        if test:
            num_levels = 0  # test done on the full level distribution
        else:
            num_levels = self.num_levels_per_env  # each environment receives a fraction of 500 levels

        env = make_procgen(self.env_name, seed, skip=self.frame_skip, num_levels=num_levels)


        if save_video:
            from gym.wrappers import Monitor
            env = Monitor(env, directory=save_path, force=True, video_callable=video_callable, uid=uid)
        return ProcgenWrapper(env, discount=self.discount, cvt_string=self.cvt_string)

    def scalar_reward_loss(self, prediction, target):
        return -(torch.log_softmax(prediction, dim=1) * target).sum(1)

    def scalar_value_loss(self, prediction, target):
        return -(torch.log_softmax(prediction, dim=1) * target).sum(1)

    def set_transforms(self):
        if self.use_augmentation:
            self.transforms = Transforms(self.augmentation, image_shape=(self.obs_shape[1], self.obs_shape[2]))

    def transform(self, images):
        return self.transforms.transform(images)


game_config = ProcgenConfig()
