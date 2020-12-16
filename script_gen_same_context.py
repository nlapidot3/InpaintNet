import click
import random

from DatasetManager.dataset_manager import DatasetManager
from DatasetManager.the_session.folk_dataset import FolkDataset
from DatasetManager.metadata import TickMetadata, \
    BeatMarkerMetadata
from LatentRNN.latent_rnn_trainer import *
from LatentRNN.latent_rnn_tester import *
from AnticipationRNN.anticipation_rnn_tester import *
from MeasureVAE.vae_tester import *
from utils.helpers import *


@click.command()
@click.option('--note_embedding_dim', default=10,
              help='size of the note embeddings')
@click.option('--metadata_embedding_dim', default=2,
              help='size of the metadata embeddings')
@click.option('--num_encoder_layers', default=2,
              help='number of layers in encoder RNN')
@click.option('--encoder_hidden_size', default=512,
              help='hidden size of the encoder RNN')
@click.option('--encoder_dropout_prob', default=0.5,
              help='float, amount of dropout prob between encoder RNN layers')
@click.option('--has_metadata', default=True,
              help='bool, True if data contains metadata')
@click.option('--latent_space_dim', default=256,
              help='int, dimension of latent space parameters')
@click.option('--num_decoder_layers', default=2,
              help='int, number of layers in decoder RNN')
@click.option('--decoder_hidden_size', default=512,
              help='int, hidden size of the decoder RNN')
@click.option('--decoder_dropout_prob', default=0.5,
              help='float, amount got dropout prob between decoder RNN layers')
@click.option('--num_latent_rnn_layers', default=2,
              help='number of layers in measure RNN')
@click.option('--latent_rnn_hidden_size', default=512,
              help='hidden size of the measure RNN')
@click.option('--latent_rnn_dropout_prob', default=0.5,
              help='float, amount of dropout prob between measure RNN layers')
@click.option('--num_layers', default=2,
              help='number of layers of the LSTMs')
@click.option('--lstm_hidden_size', default=256,
              help='hidden size of the LSTMs')
@click.option('--dropout_lstm', default=0.2,
              help='amount of dropout between LSTM layers')
@click.option('--input_dropout', default=0.2,
              help='amount of dropout between LSTM layers')
@click.option('--linear_hidden_size', default=256,
              help='hidden size of the Linear layers')
@click.option('--batch_size', default=16,
              help='training batch size')
@click.option('--num_target', default=2,
              help='number of measures to generate')
@click.option('--num_models', default=4,
              help='number of models to test')
def main(note_embedding_dim,
         metadata_embedding_dim,
         num_encoder_layers,
         encoder_hidden_size,
         encoder_dropout_prob,
         latent_space_dim,
         num_decoder_layers,
         decoder_hidden_size,
         decoder_dropout_prob,
         has_metadata,
         num_latent_rnn_layers,
         latent_rnn_hidden_size,
         latent_rnn_dropout_prob,
         num_layers,
         lstm_hidden_size,
         dropout_lstm,
         input_dropout,
         linear_hidden_size,
         batch_size,
         num_target,
         num_models
         ):

    random.seed(0)

    # init dataset
    dataset_manager = DatasetManager()
    metadatas = [
        BeatMarkerMetadata(subdivision=6),
        TickMetadata(subdivision=6)
    ]
    mvae_train_kwargs = {
        'metadatas': metadatas,
        'sequences_size': 32,
        'num_bars': 16,
        'train': True
    }
    folk_dataset_vae: FolkDataset = dataset_manager.get_dataset(
        name='folk_4by4nbars_train',
        **mvae_train_kwargs
    )
    # init vae model
    vae_model = MeasureVAE(
        dataset=folk_dataset_vae,
        note_embedding_dim=note_embedding_dim,
        metadata_embedding_dim=metadata_embedding_dim,
        num_encoder_layers=num_encoder_layers,
        encoder_hidden_size=encoder_hidden_size,
        encoder_dropout_prob=encoder_dropout_prob,
        latent_space_dim=latent_space_dim,
        num_decoder_layers=num_decoder_layers,
        decoder_hidden_size=decoder_hidden_size,
        decoder_dropout_prob=decoder_dropout_prob,
        has_metadata=has_metadata
    )
    vae_model.load()  # VAE model must be pre-trained
    if torch.cuda.is_available():
        vae_model.cuda()
    folk_train_kwargs = {
        'metadatas': metadatas,
        'sequences_size': 32,
        'num_bars': 16,
        'train': True
    }
    folk_test_kwargs = {
        'metadatas': metadatas,
        'sequences_size': 32,
        'num_bars': 16,
        'train': False
    }
    folk_dataset_train: FolkDataset = dataset_manager.get_dataset(
        name='folk_4by4nbars_train',
        **folk_train_kwargs
    )
    folk_dataset_test: FolkDataset = dataset_manager.get_dataset(
        name='folk_4by4nbars_train',
        **folk_test_kwargs
    )

    # Initialize stuff
    test_filenames = folk_dataset_test.dataset_filenames
    num_melodies = 32
    num_measures = 16
    req_length = num_measures * 4 * 6
    num_past = 6
    num_future = 6
    num_target = 4
    cur_dir = os.path.dirname(os.path.realpath(__file__))
    save_folder = 'saved_midi/'

    # Initialize models and testers
    latent_rnn_model = LatentRNN(
        dataset=folk_dataset_train,
        vae_model=vae_model,
        num_rnn_layers=num_latent_rnn_layers,
        rnn_hidden_size=latent_rnn_hidden_size,
        dropout=latent_rnn_dropout_prob,
        rnn_class=torch.nn.GRU,
        auto_reg=False,
        teacher_forcing=True
    )
    latent_rnn_model.load()  # latent_rnn model must be pre-trained
    if torch.cuda.is_available():
        latent_rnn_model.cuda()
    latent_rnn_tester = LatentRNNTester(
        dataset=folk_dataset_test,
        model=latent_rnn_model
    )

    def process_latent_rnn_batch(score_tensor, num_past=6, num_future=6, num_target=4):
        assert(num_past + num_future + num_target == 16)
        score_tensor = score_tensor.unsqueeze(0)
        score_tensor = LatentRNNTrainer.split_to_measures(score_tensor, 24)
        tensor_past, tensor_future, tensor_target = LatentRNNTrainer.split_score(
            score_tensor=score_tensor,
            num_past=num_past,
            num_future=num_future,
            num_target=num_target,
            measure_seq_len=24
        )
        return tensor_past, tensor_future, tensor_target

    # Second save latent_rnn generations
    for i in tqdm(range(num_melodies)):
        f = test_filenames[i]
        f_id = f[:-4]
        if f_id == 'tune_16154':
            for j in range(15):
                save_filename = os.path.join(cur_dir, save_folder + f_id + '_' + str(j) + '_latent_rnn.mid')
                f = os.path.join(folk_dataset_test.corpus_it_gen.raw_dataset_dir, f)
                score = folk_dataset_test.corpus_it_gen.get_score_from_path(f, fix_and_expand=True)
                score_tensor = folk_dataset_test.get_score_tensor(score)
                # ignore scores with less than 16 measures
                if score_tensor.size(1) < req_length:
                    continue
                score_tensor = score_tensor[:, :req_length]
                # metadata_tensor = metadata_tensor[:, :req_length, :]
                # save regeneration using latent_rnn
                tensor_past, tensor_future, tensor_target = process_latent_rnn_batch(score_tensor, num_past, num_future, num_target)
                # forward pass through latent_rnn
                weights, gen_target, _ = latent_rnn_tester.model(
                    past_context=tensor_past,
                    future_context=tensor_future,
                    target=tensor_target,
                    measures_to_generate=num_target,
                    train=False,
                )
                # convert to score
                batch_size, _, _ = gen_target.size()
                gen_target = gen_target.view(batch_size, num_target, 24)
                gen_score_tensor = torch.cat((tensor_past, gen_target, tensor_future), 1)
                latent_rnn_score = folk_dataset_test.tensor_to_score(gen_score_tensor.cpu())
                latent_rnn_score.write('midi', fp=save_filename)


if __name__ == '__main__':
    main()
