# Copyright (C) 2020 IDIR Lab - UT Arlington
#
#     This program is free software: you can redistribute it and/or modify
#     it under the terms of the GNU General Public License v3 as published by
#     the Free Software Foundation.
#
#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#     GNU General Public License for more details.
#
#     You should have received a copy of the GNU General Public License
#     along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# Contact Information:
#     See: https://idir.uta.edu/cli.html
#
#     Chengkai Li
#     Box 19015
#     Arlington, TX 76019
#
import tensorflow as tf


class PoolerLayer(tf.keras.layers.Layer):
    def __init__(self, hidden_size, **kwargs):
        super(PoolerLayer, self).__init__(**kwargs)

        self.hidden_size = hidden_size
        self.dense_layer = tf.keras.layers.Dense(hidden_size, activation='tanh', name='dense')

    def call(self, x, **kwargs):
        return self.dense_layer(x)
