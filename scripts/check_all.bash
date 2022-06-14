DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PWD=`pwd`
cd $DIR
black -l 120 $DIR/../Mergin
cd $PWD
