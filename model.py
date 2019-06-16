import tensorflow as tf
import numpy as np
import os
from keras.preprocessing.sequence import pad_sequences
from keras.utils import to_categorical
from models.recurrent import RecurrentModel
from models.embeddings import Embedding
from sklearn.metrics import f1_score
import math
from flags import FLAGS


class ClaimBusterModel:
    def __init__(self, vocab, cls_weights):
        self.x = tf.placeholder(tf.int32, (None, FLAGS.max_len), name='x')
        self.x_len = tf.placeholder(tf.int32, (None,), name='x_len')
        self.output_mask = tf.placeholder(tf.bool, (None, FLAGS.max_len), name='output_mask')
        self.y = tf.placeholder(tf.int32, (None, FLAGS.num_classes), name='y')
        self.kp_emb = tf.placeholder(tf.float32, name='kp_emb')
        self.kp_lstm = tf.placeholder(tf.float32, name='kp_lstm')
        self.cls_weight = tf.placeholder(tf.float32, (None,), name='cls_weight')

        self.embed_obj = Embedding(vocab)
        self.embed = self.embed_obj.construct_embeddings()

        self.computed_cls_weights = cls_weights

        self.logits, self.cost = self.construct_model(adv=FLAGS.adv_train)
        self.optimizer = tf.train.AdamOptimizer(learning_rate=FLAGS.learning_rate).minimize(self.cost)\
            if FLAGS.adam else tf.train.RMSPropOptimizer(learning_rate=FLAGS.learning_rate).minimize(self.cost)

        self.y_pred = tf.nn.softmax(self.logits, axis=1, name='y_pred')
        self.correct = tf.equal(tf.argmax(self.y, axis=1), tf.argmax(self.y_pred, axis=1))
        self.acc = tf.reduce_mean(tf.cast(self.correct, tf.float32), name='acc')

    def construct_model(self, adv):
        orig_embed, logits = self.fprop()
        loss = self.ce_loss(logits, self.cls_weight)

        if adv:
            logits_adv = self.fprop(orig_embed, loss, adv=True)
            loss += FLAGS.adv_coeff * self.adv_loss(logits_adv, self.cls_weight)

        return logits, tf.identity(loss, name='cost')

    def fprop(self, orig_embed=None, reg_loss=None, adv=False):
        if adv: assert (reg_loss is not None and orig_embed is not None)

        with tf.variable_scope('cb_model', reuse=(True if adv else False)):
            lstm_out = RecurrentModel.build_lstm(self.x, self.x_len, self.output_mask, self.embed, self.kp_emb,
                                                 self.kp_lstm, orig_embed, reg_loss, adv)
            if not adv:
                orig_embed, lstm_out = lstm_out

            output_weights = tf.get_variable('cb_output_weights', shape=(FLAGS.rnn_cell_size * (2 if FLAGS.bidir_lstm else 1), FLAGS.num_classes),
                                             initializer=tf.contrib.layers.xavier_initializer())
            output_biases = tf.get_variable('cb_output_biases', shape=FLAGS.num_classes,
                                            initializer=tf.zeros_initializer())

            cb_out = tf.matmul(lstm_out, output_weights) + output_biases

            return (orig_embed, cb_out) if not adv else cb_out

    def adv_loss(self, logits, cls_weight):
        return tf.identity(self.ce_loss(logits, cls_weight), name='adv_loss')

    def ce_loss(self, logits, cls_weight):
        loss = tf.nn.softmax_cross_entropy_with_logits_v2(labels=self.y, logits=logits)
        loss_l2 = 0

        if FLAGS.l2_reg_coeff > 0.0:
            varlist = tf.trainable_variables()
            loss_l2 = tf.add_n([tf.nn.l2_loss(v) for v in varlist if 'bias' not in v.name]) * FLAGS.l2_reg_coeff

        ret_loss = loss + loss_l2
        if FLAGS.weight_classes_loss:
            ret_loss *= cls_weight

        return tf.identity(ret_loss, name='reg_loss')

    def train_neural_network(self, sess, batch_x, batch_y):
        sess.run(
            self.optimizer,
            feed_dict={
                self.x: self.pad_seq(batch_x),
                self.x_len: self.gen_x_len(batch_x),
                self.y: self.one_hot(batch_y),
                self.output_mask: self.gen_output_mask(batch_x),
                self.kp_emb: 1.0,
                self.kp_lstm: 1.0,
                self.cls_weight: self.get_cls_weights(batch_y)
            }
        )

    def execute_validation(self, sess, test_data):
        n_batches = math.ceil(float(FLAGS.test_examples) / float(FLAGS.batch_size))
        val_loss, val_acc = 0.0, 0.0
        tot_val_ex = 0

        all_y_pred = []
        all_y = []
        for batch in range(n_batches):
            batch_x, batch_y = self.get_batch(batch, test_data, ver='validation')
            tloss, tacc, tpred = self.stats_from_run(sess, batch_x, batch_y)

            val_loss += tloss
            val_acc += tacc * len(batch_y)
            tot_val_ex += len(batch_y)

            all_y_pred = np.concatenate((all_y_pred, tpred))
            all_y = np.concatenate((all_y, batch_y))

        val_loss /= tot_val_ex
        val_acc /= tot_val_ex
        val_f1 = f1_score(all_y, all_y_pred, average='weighted')

        return 'DJ Val Loss: {:>7.4f} DJ Val F1: {:>7.4f} '.format(val_loss, val_f1)

    def stats_from_run(self, sess, batch_x, batch_y):
        run_loss = sess.run(
            self.cost,
            feed_dict={
                self.x: self.pad_seq(batch_x),
                self.x_len: self.gen_x_len(batch_x),
                self.y: self.one_hot(batch_y),
                self.output_mask: self.gen_output_mask(batch_x),
                self.kp_emb: 1.0,
                self.kp_lstm: 1.0,
                self.cls_weight: self.get_cls_weights(batch_y)
            }
        )
        run_acc = sess.run(
            self.acc,
            feed_dict={
                self.x: self.pad_seq(batch_x),
                self.x_len: self.gen_x_len(batch_x),
                self.y: self.one_hot(batch_y),
                self.output_mask: self.gen_output_mask(batch_x),
                self.kp_emb: 1.0,
                self.kp_lstm: 1.0,
                self.cls_weight: self.get_cls_weights(batch_y)
            }
        )
        run_pred = sess.run(
            self.y_pred,
            feed_dict={
                self.x: self.pad_seq(batch_x),
                self.x_len: self.gen_x_len(batch_x),
                self.y: self.one_hot(batch_y),
                self.output_mask: self.gen_output_mask(batch_x),
                self.kp_emb: 1.0,
                self.kp_lstm: 1.0,
                self.cls_weight: self.get_cls_weights(batch_y)
            }
        )

        return np.sum(run_loss), run_acc, np.argmax(run_pred, axis=1)

    def get_cls_weights(self, batch_y):
        return [self.computed_cls_weights[z] for z in batch_y]

    @staticmethod
    def pad_seq(inp):
        return pad_sequences(inp, padding="post", maxlen=FLAGS.max_len)

    @staticmethod
    def one_hot(a):
        return to_categorical(a, num_classes=FLAGS.num_classes)

    @staticmethod
    def gen_output_mask(batch_x):
        return [[1 if j == len(el) - 1 else 0 for j in range(FLAGS.max_len)] for el in batch_x]

    @staticmethod
    def gen_x_len(batch_x):
        return [len(el) for el in batch_x]

    @staticmethod
    def save_model(sess, epoch):
        saver = tf.train.Saver()
        saver.save(sess, os.path.join(FLAGS.output_dir, 'cb.ckpt'), global_step=epoch)

    @staticmethod
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