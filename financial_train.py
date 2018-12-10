import os
import datetime
import torch
from torch import nn, optim
import numpy as np
from models import HawkesDecayRNN
from train_functions import train_decayrnn, plot_loss
from utils.save_model import save_model
import pandas as pd
from argparse import ArgumentParser

parser = ArgumentParser(description="Train the model on financial data.")
parser.add_argument('--data', type=str, required=True, nargs='+',
                    help='Location to find the financial data file.')
parser.add_argument('-e', '--epochs', type=int, required=True,
                    help='Number of epochs.')
parser.add_argument('--lr', type=float,
                    default=5e-3, dest='learning_rate',
                    help="Learning rate.")
parser.add_argument('--cuda', action='store_true',
                    help="Whether or not to use GPU acceleration.")

args = parser.parse_args()
data_files = args.data  # data path
data_files.sort()

frames_ = []
for file in data_files:
    df_ = pd.read_csv(file)
    day_stamp = df_.Date.values[0]
    print("Day", day_stamp)
    frames_.append(df_)

df = pd.concat(frames_, ignore_index=True)


# Arrange our data
evt_times = df.Time.values
evt_types = (df.Side.values + 1) // 2  # 0 is ask, 1 is bid

print("Sequence length:", len(evt_times))
num_of_splits = int(input("Number of splits: "))
print("Split sequence lengths:", len(evt_times)/num_of_splits)

split_times_list = np.array_split(evt_times, num_of_splits)
split_types_list = np.array_split(evt_types, num_of_splits)
seq_lengths = [len(e) for e in split_times_list]
split_times_list = [torch.from_numpy(e) for e in split_times_list]
split_types_list = [torch.from_numpy(e) for e in split_types_list]
seq_lengths = torch.LongTensor(seq_lengths) - 1
seq_times = nn.utils.rnn.pad_sequence(split_times_list, batch_first=True).to(torch.float32)
seq_types = nn.utils.rnn.pad_sequence(split_types_list, batch_first=True)

if args.cuda:
    seq_lengths = seq_lengths.cuda()
    seq_times = seq_times.cuda()
    seq_types = seq_types.cuda()

# Define model
process_dim = 2
hidden_size = 128

model = HawkesDecayRNN(process_dim, hidden_size)
MODEL_NAME = model.__class__.__name__
if args.cuda:
    model = model.cuda()
num_of_parameters = sum(e.numel() for e in model.parameters())
print("no. of model parameters:", num_of_parameters)

# Train model
EPOCHS = args.epochs
BATCH_SIZE = 32

optimizer = optim.Adam(model.parameters(), lr=args.learning_rate)
loss = train_decayrnn(model, optimizer, seq_times, seq_types, seq_lengths, -1,  # tmax actually doesn't matter
                      BATCH_SIZE, EPOCHS, use_cuda=args.cuda)

# Model file dump
SAVED_MODELS_PATH = os.path.abspath('saved_models')
os.makedirs(SAVED_MODELS_PATH, exist_ok=True)
# print("Saved models directory: {}".format(SAVED_MODELS_PATH))

date_format = "%Y%m%d-%H%M%S"
now_timestamp = datetime.datetime.now().strftime(date_format)
extra_tag = "{}d".format(process_dim)
filename_base = "{}-{}_hidden{}-{}".format(
    MODEL_NAME, extra_tag,
    hidden_size, now_timestamp)

save_model(model, data_files, extra_tag,
           hidden_size, now_timestamp, MODEL_NAME)

# Plot loss and save
filename_loss_plot = "logs/loss_plot_" + filename_base + ".png"
fig = plot_loss(EPOCHS, loss)
fig.savefig(filename_loss_plot)
