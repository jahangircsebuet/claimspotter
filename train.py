import tensorflow as tf
from keras.preprocessing.sequence import pad_sequences
from keras.utils import to_categorical
import numpy as np
import math
import time
import os
from utils.data_loader import DataLoader
from models.recurrent import RecurrentModel
from models.embeddings import Embedding
from sklearn.metrics import f1_score
from flags import FLAGS, print_flags

x = tf.placeholder(tf.int32, (None, FLAGS.max_len), name='x')
y = tf.placeholder(tf.int32, (None, FLAGS.num_classes), name='y')
kp_emb = tf.placeholder(tf.float32, name='kp_emb')
kp_lstm = tf.placeholder(tf.float32, name='kp_lstm')
cls_weight = tf.placeholder(tf.float32, (None,), name='cls_weight')

computed_cls_weights = []


def pad_seq(inp):
    return pad_sequences(inp, padding="pre", maxlen=FLAGS.max_len)


def one_hot(a):
    return to_categorical(a, num_classes=FLAGS.num_classes)


def get_cls_weights(batch_y):
    return [computed_cls_weights[z] for z in batch_y]


def execute_validation(sess, cost, acc, y_pred, test_data):
    n_batches = math.ceil(float(FLAGS.test_examples) / float(FLAGS.batch_size))
    val_loss, val_acc = 0.0, 0.0
    tot_val_ex = 0

    all_y_pred = []
    all_y = []
    for batch in range(n_batches):
        batch_x, batch_y = get_batch(batch, test_data, ver='validation')
        tloss, tacc, tpred = validation_stats(sess, cost, acc, y_pred, batch_x, batch_y)

        val_loss += tloss
        val_acc += tacc * len(batch_y)
        tot_val_ex += len(batch_y)

        all_y_pred = np.concatenate((all_y_pred, tpred))
        all_y = np.concatenate((all_y, batch_y))

    val_loss /= tot_val_ex
    val_acc /= tot_val_ex
    val_f1 = f1_score(all_y, all_y_pred, average='weighted')

    return 'DJ Val Loss: {:>7.4f} DJ Val F1: {:>7.4f} '.format(val_loss, val_f1)


def validation_stats(sess, cost, acc, y_pred, batch_x, batch_y):
    val_loss = sess.run(
        cost,
        feed_dict={
            x: pad_seq(batch_x),
            y: one_hot(batch_y),
            kp_emb: 1.0,
            kp_lstm: 1.0,
            cls_weight: get_cls_weights(batch_y)
        }
    )
    val_acc = sess.run(
        acc,
        feed_dict={
            x: pad_seq(batch_x),
            y: one_hot(batch_y),
            kp_emb: 1.0,
            kp_lstm: 1.0,
            cls_weight: get_cls_weights(batch_y)
        }
    )
    val_pred = sess.run(
        y_pred,
        feed_dict={
            x: pad_seq(batch_x),
            y: one_hot(batch_y),
            kp_emb: 1.0,
            kp_lstm: 1.0,
            cls_weight: get_cls_weights(batch_y)
        }
    )

    return np.sum(val_loss), val_acc, np.argmax(val_pred, axis=1)


def batch_stats(sess, batch_x, batch_y, cost, acc):
    train_loss = sess.run(
        cost,
        feed_dict={
            x: pad_seq(batch_x),
            y: one_hot(batch_y),
            kp_emb: 1.0,
            kp_lstm: 1.0,
            cls_weight: get_cls_weights(batch_y)
        }
    )
    train_acc = sess.run(
        acc,
        feed_dict={
            x: pad_seq(batch_x),
            y: one_hot(batch_y),
            kp_emb: 1.0,
            kp_lstm: 1.0,
            cls_weight: get_cls_weights(batch_y)
        }
    )

    return np.sum(train_loss), train_acc


def train_neural_network(sess, optimizer, batch_x, batch_y):
    print(batch_y)
    sess.run(
        optimizer,
        feed_dict={
            x: pad_seq(batch_x),
            y: one_hot(batch_y),
            kp_emb: FLAGS.keep_prob_emb,
            kp_lstm: FLAGS.keep_prob_lstm,
            cls_weight: get_cls_weights(batch_y)
        }
    )


def get_batch(bid, data, ver='train'):
    batch_x = []
    batch_y = []

    for i in range(FLAGS.batch_size):
        idx = bid * FLAGS.batch_size + i
        if idx >= (FLAGS.train_examples if ver == 'train' else FLAGS.test_examples):
            break
        batch_x.append(data.x[idx])
        batch_y.append(data.y[idx])

    return batch_x, batch_y


def save_model(sess, epoch):
    saver = tf.train.Saver()
    saver.save(sess, os.path.join(FLAGS.output_dir, 'cb.ckpt'), global_step=epoch)


def main():
    global computed_cls_weights

    os.environ['CUDA_VISIBLE_DEVICES'] = ','.join([str(z) for z in FLAGS.gpu_active])

    print_flags()

    tf.logging.info("Loading dataset")
    data_load = DataLoader()
    computed_cls_weights = data_load.class_weights

    train_data = data_load.load_training_data()
    test_data = data_load.load_testing_data()

    tf.logging.info("{} training examples".format(train_data.get_length()))
    tf.logging.info("{} validation examples".format(test_data.get_length()))

    embed_obj = Embedding(data_load.vocab)
    embed = embed_obj.construct_embeddings()

    lstm_model = RecurrentModel()
    logits, cost = lstm_model.construct_model(x, y, embed, kp_emb, kp_lstm, cls_weight, adv=FLAGS.adv_train)
    optimizer = tf.train.AdamOptimizer(learning_rate=FLAGS.learning_rate).minimize(cost) if FLAGS.adam else \
        tf.train.RMSPropOptimizer(learning_rate=FLAGS.learning_rate).minimize(cost)

    y_pred = tf.nn.softmax(logits, axis=1, name='y_pred')
    correct = tf.equal(tf.argmax(y, axis=1), tf.argmax(y_pred, axis=1))
    acc = tf.reduce_mean(tf.cast(correct, tf.float32), name='acc')

    with tf.Session(config=tf.ConfigProto(allow_soft_placement=True)) as sess:
        sess.run(tf.global_variables_initializer())
        embed_obj.init_embeddings(sess)

        start = time.time()
        epochs_trav = 0

        tf.logging.info("Starting{}training...".format(' adversarial ' if FLAGS.adv_train else ' '))
        for epoch in range(FLAGS.max_steps):
            epochs_trav += 1
            n_batches = math.ceil(float(FLAGS.train_examples) / float(FLAGS.batch_size))

            n_samples = 0
            epoch_loss = 0.0
            epoch_acc = 0.0

            for i in range(n_batches):
                batch_x, batch_y = get_batch(i, train_data)
                train_neural_network(sess, optimizer, batch_x, batch_y)

                b_loss, b_acc = batch_stats(sess, batch_x, batch_y, cost, acc)
                epoch_loss += b_loss
                epoch_acc += b_acc * len(batch_y)
                n_samples += len(batch_y)

            epoch_loss /= n_samples
            epoch_acc /= n_samples

            if epoch % FLAGS.stat_print_interval == 0:
                log_string = 'Epoch {:>3} Loss: {:>7.4} Acc: {:>7.4f}% '.format(epoch + 1, epoch_loss,
                                                                                epoch_acc * 100)
                if test_data.get_length() > 0:
                    log_string += execute_validation(sess, cost, acc, y_pred, test_data)
                log_string += '({:3.3f} sec/epoch)'.format((time.time() - start) / epochs_trav)

                tf.logging.info(log_string)

                start = time.time()
                epochs_trav = 0

            if epoch % FLAGS.model_save_interval == 0 and epoch != 0:
                save_model(sess, epoch)
                tf.logging.info('Model @ epoch {} saved'.format(epoch + 1))

        tf.logging.info('Training complete. Saving final model...')
        save_model(sess, FLAGS.max_steps)
        tf.logging.info('Model saved.')

        sess.close()


if __name__ == '__main__':
    tf.logging.set_verbosity(tf.logging.INFO)
    main()
