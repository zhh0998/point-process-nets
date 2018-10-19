import torch
from torch import nn

device = torch.device('cpu')


class NeuralCTLSTM(nn.Module):
    """
    A continuous-time LSTM, defined according to Eisner & Mei's article
    https://arxiv.org/abs/1612.09328
    """

    def __init__(self, hidden_dim: int):
        super(NeuralCTLSTM, self).__init__()

        self.hidden_dim = hidden_dim

        self.input_g = nn.Linear(hidden_dim, hidden_dim)
        self.forget_g = nn.Linear(hidden_dim, hidden_dim)
        self.output_g = nn.Linear(hidden_dim, hidden_dim)

        self.ibar = nn.Linear(hidden_dim, hidden_dim)
        self.fbar = nn.Linear(hidden_dim, hidden_dim)

        # activation will be tanh
        self.z_gate = nn.Linear(hidden_dim, hidden_dim)

        # Cell decay factor
        self.decay = nn.Linear(hidden_dim, hidden_dim)
        # we can learn the parameters of this
        self.decay_act = nn.Softplus()

        # The hidden state contains
        # the cell state at t, the target cell state
        self.init_hidden()

        self.activation = nn.Softplus()
        self.weight_f = torch.rand(self.hidden_dim, device=device)

    def init_hidden(self, batch_size=1):
        """
        Initialize the hidden state, and the two hidden memory
        cells c and cbar.
        """
        self.hidden = (torch.rand(batch_size, self.hidden_dim, device=device),
                       torch.rand(batch_size, self.hidden_dim, device=device),
                       torch.rand(batch_size, self.hidden_dim, device=device))

    def c_func(self, dt: torch.Tensor, c: torch.Tensor,
               cbar: torch.Tensor, decay: torch.Tensor):
        """
        Compute the decayed cell memory c(t) = c(ti + dt)
        """
        # print("Computing decayed cell memory...")
        # print(c.shape, type(c))
        # print(cbar.shape, type(cbar))
        # print(decay.shape, type(decay))
        dt = dt.unsqueeze(-1)
        # print(dt, type(dt))
        return cbar + (c - cbar) * torch.exp(-decay * dt)

    def next_event(self, output, dt, decay):
        # h_ti, c_ti, cbar = self.hidden
        # c_t_after = self.c_func(dt, c_ti, cbar, decay)
        # h_t_after = output * torch.tanh(c_t_after)
        # lbdaMax = h_t_after
        raise NotImplementedError

    def forward(self, inter_times):
        """
        inter_times: inter-arrival time for the next event in the sequence

        Returns:
            output : result of the output gate
            h_ti   : hidden state
            c_ti   : cell state
            cbar   : cell target
            decay_t: decay parameter on the interval
        #TODO event type embedding
        """
        # get the hidden state and memory from before
        h_ti, c_ti, cbar = self.hidden

        # TODO concatenate event embedding with ht
        v = torch.cat((h_ti,))
        input = torch.sigmoid(self.input_g(v))
        forget = torch.sigmoid(self.forget_g(v))
        output = torch.sigmoid(self.output_g(v))

        input_bar = torch.sigmoid(self.ibar(v))
        forget_bar = torch.sigmoid(self.fbar(v))

        # Not-quite-c
        zi = torch.tanh(self.z_gate(v))

        # Compute the decay parameter
        decay_t = self.decay_act(self.decay(v))

        # Now update the cell memory
        # Decay the cell memory
        c_t_after = self.c_func(inter_times, c_ti, cbar, decay_t)
        # Update the cell
        c_ti = forget * c_t_after + input * zi
        # Update the cell state asymptotic value
        cbar = forget_bar * cbar + input_bar * zi
        h_ti = output * torch.tanh(c_t_after)

        # Store our new states for the next pass to use
        self.hidden = h_ti, c_ti, cbar
        return output, h_ti, c_ti, cbar, decay_t

    def eval_intensity(self, dt, output, c_ti, cbar, decay):
        """
        Compute the intensity function
        t:      time to compute
        output: NN output o_i
        c_ti:   previous cell state
        cbar:   previous cell target
        decay:

        It is best to store the training history in variables for this.
        """
        # Get the updated c(t)
        c_t_after = self.c_func(dt, c_ti, cbar, decay)
        h_t = output * torch.tanh(c_t_after)
        try:
            pre_lambda = torch.mm(self.weight_f[None, :], h_t.t())
        except BaseException:
            print("Error occured in c_func")
            print(" dt shape %s" % str(dt.shape))
            print(" Weights shape %s" % str(self.weight_f.shape))
            print(" h_t shape %s" % str(h_t.shape))

            raise
        return self.activation(pre_lambda)

    def likelihood(self, event_times, c_ti, cbar, output, decay, T):
        """
        Compute the negative log-likelihood as a loss function
        #lengths: real sequence lengths
        c_ti :  entire cell state history
        output: entire output history
        decay:  entire decay history
        """
        inter_times = event_times[-1:] - event_times[1:]
        print("inter_times shape: %s" % str(inter_times.shape))
        # Get the intensity process
        event_intensities = [
            self.eval_intensity(inter_times[i], output[i],
                                c_ti[i], cbar[i], decay[i])
            for i in range(inter_times.size(0))
        ]
        event_intensities = torch.stack(event_intensities)
        print("event intensities shape %s" % str(event_intensities.shape))
        first_sum = event_intensities.log().sum(dim=0)
        print("first_sum shape %s" % str(first_sum.shape))

        # The integral term is computed using a Monte Carlo method
        batch_size = output.size(1)
        # random samples in [0, T]
        samples, _ = (T * torch.rand(event_times.size(0), batch_size)).sort(0)
        # get the corresponding intervals each sample belongs to
        mask_idx = torch.cumsum((samples >= event_times), dim=0)
        print("mask dim %s" % str(mask_idx.shape))
        mask_idx = mask_idx[:-1]
        print(mask_idx)

        dsamples = samples[:-1] - samples[1:]
        ioutput = output[mask_idx]
        print("  ioutput.shape %s" % str(ioutput.shape))
        ic_ti = c_ti[mask_idx]
        icbar = cbar[mask_idx]
        idecay = decay[mask_idx]
        lam_samples = torch.stack([
            self.eval_intensity(dsamples[i], ioutput[i],
                                ic_ti[i], icbar[i], idecay[i])
            for i in range(output.size(0))
        ])
        print("lam samples shape %s" % str(lam_samples.shape))
        integral = torch.mean(lam_samples, dim=0)
        print("integral shape %s" % str(integral.shape))
        # Tensor of dim. batch_size
        # of the values of the likelihood
        res = first_sum - integral
        # return the opposite of the mean of that
        # loss
        return -res.mean()
